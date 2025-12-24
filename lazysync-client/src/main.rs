use axum::{
    extract::Json,
    http::StatusCode,
    response::Json as ResponseJson,
    routing::post,
    Router,
};
use rfb_client::{Client, FileEntry, Response, get_path_from_cache, update_cache_with_response};
use serde::{Deserialize, Serialize};
use std::sync::{Arc, Mutex};
use tokio::sync::oneshot;
use tower::ServiceBuilder;
use tower_http::cors::CorsLayer;

// ===== HTTP API 请求结构 =====
#[derive(Deserialize)]
struct PathRequest {
    path: String,
}

#[derive(Serialize)]
struct PathResponse {
    success: bool,
    message: String,
}

#[derive(Serialize)]
struct GetPathResponse {
    success: bool,
    path: String,
    entries: Vec<FileEntry>,
    from_cache: bool,
}

// ===== Cache 管理 =====
const CACHE_FILE: &str = "cache.json";

type CacheData = HashMap<String, Vec<FileEntry>>;

fn load_cache() -> CacheData {
    if Path::new(CACHE_FILE).exists() {
        if let Ok(content) = fs::read_to_string(CACHE_FILE) {
            if let Ok(cache) = serde_json::from_str::<CacheData>(&content) {
                return cache;
            }
        }
    }
    HashMap::new()
}

fn save_cache(cache: &CacheData) -> std::io::Result<()> {
    let content = serde_json::to_string_pretty(cache)?;
    fs::write(CACHE_FILE, content)?;
    Ok(())
}

fn update_cache_with_response(resp: &Response) -> std::io::Result<()> {
    let mut cache = load_cache();

    // 遍历所有目录数据并更新cache
    for dir_map in &resp.data {
        for (abs_path, entries) in dir_map {
            // 将FileInfo转换为FileEntry格式（用于cache兼容性）
            // 使用权限字符串的第一个字符判断是否为目录（'d'表示目录）
            let file_entries: Vec<FileEntry> = entries.iter().map(|fi| {
                let is_dir = fi.permissions.chars().next() == Some('d');
                FileEntry {
                    name: fi.name.clone(),
                    is_dir,
                    size: fi.size,
                    permissions: fi.permissions.clone(),
                    modified: fi.modified.clone(),
                }
            }).collect();
            cache.insert(abs_path.clone(), file_entries);
        }
    }

    save_cache(&cache)
}

fn get_path_from_cache(path: &str) -> Option<Vec<FileEntry>> {
    let cache = load_cache();
    cache.get(path).cloned()
}

// ===== 客户端主函数 =====
#[tokio::main]
async fn main() -> std::io::Result<()> {
    // 连接TCP服务器
    let stream = TcpStream::connect("127.0.0.1:9000")?;
    stream.set_nodelay(true)?;
    println!("Connected to server.");

    let writer = stream.try_clone()?;
    let reader = BufReader::new(stream);

    // 共享状态
    let recent = Arc::new(Mutex::new(Option::<String>::None));
    let req_id = Arc::new(Mutex::new(0u64));
    let writer_mutex = Arc::new(Mutex::new(writer));
    let response_channels: Arc<Mutex<HashMap<u64, oneshot::Sender<Response>>>> = Arc::new(Mutex::new(HashMap::new()));

    // 接收线程：处理服务器响应并更新cache
    {
        let response_channels_clone = Arc::clone(&response_channels);
        thread::spawn(move || {
            for line in reader.lines().flatten() {
                // 打印收到的原始响应
                println!("=== Received raw response ===");
                println!("{}", line);
                println!("=============================");
                
                match serde_json::from_str::<Response>(&line) {
                    Ok(resp) => {
                        println!("[{}] Successfully parsed response for path: {}", resp.id, resp.path);
                        println!("Response contains {} directory entries", resp.data.len());
                        for (idx, dir_map) in resp.data.iter().enumerate() {
                            for (abs_path, entries) in dir_map {
                                println!("  Entry {}: path={}, entries_count={}", idx, abs_path, entries.len());
                            }
                        }

                        // 检查是否有等待的channel
                        {
                            let mut channels = response_channels_clone.lock().unwrap();
                            if let Some(sender) = channels.remove(&resp.id) {
                                let _ = sender.send(resp.clone());
                            }
                        }

                        // 更新cache
                        if let Err(e) = update_cache_with_response(&resp) {
                            eprintln!("Failed to update cache: {}", e);
                        }
                    }
                    Err(e) => {
                        eprintln!("Failed to parse response: {}", e);
                        eprintln!("Raw response was: {}", line);
                    }
                }
            }
        });
    }

    // 定时刷新最近路径
    {
        let recent = Arc::clone(&recent);
        let writer_mutex = Arc::clone(&writer_mutex);
        let req_id = Arc::clone(&req_id);

        thread::spawn(move || loop {
            thread::sleep(Duration::from_secs(3));
            let path_opt: Option<String> = {
                let r = recent.lock().unwrap();
                r.clone()
            };

            if let Some(path) = path_opt {
                let mut id = req_id.lock().unwrap();
                *id += 1;
                let req = Request {
                    id: *id,
                    path: path.clone(),
                };
                if let Ok(mut w) = writer_mutex.lock() {
                    writeln!(w, "{}", serde_json::to_string(&req).unwrap()).ok();
                }
            }
        });
    }

    // 创建HTTP服务器
    let app = Router::new()
        .route("/request", post(handle_request))
        .route("/get", post(handle_get))
        .layer(
            ServiceBuilder::new()
                .layer(CorsLayer::permissive())
                .into_inner(),
        )
        .with_state((recent.clone(), req_id.clone(), writer_mutex.clone(), response_channels.clone()));

    println!("Starting HTTP server on http://127.0.0.1:8080");
    println!("Use POST /request with JSON body: {{\"path\": \"/your/path\"}}");

    let listener = tokio::net::TcpListener::bind("127.0.0.1:8080").await?;
    axum::serve(listener, app).await?;

    Ok(())
}

// HTTP处理函数
async fn handle_request(
    axum::extract::State((recent, req_id, writer_mutex, _)): axum::extract::State<(
        Arc<Mutex<Option<String>>>,
        Arc<Mutex<u64>>,
        Arc<Mutex<TcpStream>>,
        Arc<Mutex<HashMap<u64, oneshot::Sender<Response>>>>,
    )>,
    Json(payload): Json<PathRequest>,
) -> Result<ResponseJson<PathResponse>, StatusCode> {
    let path = payload.path.trim().to_string();
    if path.is_empty() {
        return Err(StatusCode::BAD_REQUEST);
    }

    // 更新最近路径（只保留最新的）
    {
        let mut r = recent.lock().unwrap();
        *r = Some(path.clone());
    }

    // 发送请求
    let mut id = req_id.lock().unwrap();
    *id += 1;
    let req = Request {
        id: *id,
        path: path.clone(),
    };

    if let Ok(mut writer) = writer_mutex.lock() {
        if writeln!(writer, "{}", serde_json::to_string(&req).unwrap()).is_ok() {
            writer.flush().ok();
            Ok(ResponseJson(PathResponse {
                success: true,
                message: format!("Request sent for path: {}", path),
            }))
        } else {
            Err(StatusCode::INTERNAL_SERVER_ERROR)
        }
    } else {
        Err(StatusCode::INTERNAL_SERVER_ERROR)
    }
}

// 新的HTTP处理函数：获取路径数据（带cache检查）
async fn handle_get(
    axum::extract::State((recent, req_id, writer_mutex, response_channels)): axum::extract::State<(
        Arc<Mutex<Option<String>>>,
        Arc<Mutex<u64>>,
        Arc<Mutex<TcpStream>>,
        Arc<Mutex<HashMap<u64, oneshot::Sender<Response>>>>,
    )>,
    Json(payload): Json<PathRequest>,
) -> Result<ResponseJson<GetPathResponse>, StatusCode> {
    let path = payload.path.trim().to_string();
    if path.is_empty() {
        return Err(StatusCode::BAD_REQUEST);
    }

    // 1. 先检查cache
    if let Some(entries) = get_path_from_cache(&path) {
        // 有cache，更新recent并返回
        {
            let mut r = recent.lock().unwrap();
            *r = Some(path.clone());
        }
        return Ok(ResponseJson(GetPathResponse {
            success: true,
            path: path.clone(),
            entries,
            from_cache: true,
        }));
    }

    // 2. 没有cache，更新recent，发送请求并等待响应
    {
        let mut r = recent.lock().unwrap();
        *r = Some(path.clone());
    }

    // 创建channel等待响应
    let (tx, rx) = oneshot::channel();
    let request_id = {
        let mut id = req_id.lock().unwrap();
        *id += 1;
        let req_id = *id;
        
        // 注册channel
        {
            let mut channels = response_channels.lock().unwrap();
            channels.insert(req_id, tx);
        }

        // 发送请求
        let req = Request {
            id: req_id,
            path: path.clone(),
        };

        if let Ok(mut writer) = writer_mutex.lock() {
            if writeln!(writer, "{}", serde_json::to_string(&req).unwrap()).is_ok() {
                writer.flush().ok();
            } else {
                // 发送失败，清理channel
                let mut channels = response_channels.lock().unwrap();
                channels.remove(&req_id);
                return Err(StatusCode::INTERNAL_SERVER_ERROR);
            }
        } else {
            // 获取writer失败，清理channel
            let mut channels = response_channels.lock().unwrap();
            channels.remove(&req_id);
            return Err(StatusCode::INTERNAL_SERVER_ERROR);
        }

        req_id
    };

    // 等待响应（最多等待5秒）
    match tokio::time::timeout(Duration::from_secs(5), rx).await {
        Ok(Ok(resp)) => {
            // 响应已收到，cache已在接收线程中更新
            // 从响应数据中查找请求的路径（尝试规范化路径匹配）
            let request_path_buf = std::path::PathBuf::from(&path);
            let canonical_request_path = request_path_buf.canonicalize()
                .unwrap_or_else(|_| request_path_buf.clone())
                .display()
                .to_string();
            
            let mut found_entries: Vec<FileEntry> = Vec::new();
            let mut response_path = path.clone();
            
            // 在data中查找请求的路径
            for dir_map in &resp.data {
                for (abs_path, file_infos) in dir_map {
                    // 比较绝对路径（尝试规范化）
                    let abs_path_buf = std::path::PathBuf::from(abs_path);
                    let normalized_resp_path = abs_path_buf.canonicalize()
                        .unwrap_or_else(|_| abs_path_buf.clone())
                        .display()
                        .to_string();
                    
                    // 直接比较字符串或规范化后的路径
                    if abs_path == &path || abs_path == &canonical_request_path 
                        || normalized_resp_path == canonical_request_path 
                        || normalized_resp_path == path {
                        // 找到匹配的路径，转换FileInfo为FileEntry
                        // 使用权限字符串的第一个字符判断是否为目录（'d'表示目录）
                        found_entries = file_infos.iter().map(|fi| {
                            let is_dir = fi.permissions.chars().next() == Some('d');
                            FileEntry {
                                name: fi.name.clone(),
                                is_dir,
                                size: fi.size,
                                permissions: fi.permissions.clone(),
                                modified: fi.modified.clone(),
                            }
                        }).collect();
                        response_path = abs_path.clone();
                        break;
                    }
                }
                if !found_entries.is_empty() {
                    break;
                }
            }
            
            // 如果没找到，返回空列表（可能路径不存在或不是目录）
            Ok(ResponseJson(GetPathResponse {
                success: true,
                path: response_path,
                entries: found_entries,
                from_cache: false,
            }))
        }
        Ok(Err(_)) => {
            // channel错误
            let mut channels = response_channels.lock().unwrap();
            channels.remove(&request_id);
            Err(StatusCode::INTERNAL_SERVER_ERROR)
        }
        Err(_) => {
            // 超时
            let mut channels = response_channels.lock().unwrap();
            channels.remove(&request_id);
            Err(StatusCode::REQUEST_TIMEOUT)
        }
    }
}
