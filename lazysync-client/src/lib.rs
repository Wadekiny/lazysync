use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    fs,
    io::{BufRead, BufReader, Write},
    net::TcpStream,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::sync::oneshot;

// ===== 协议结构 =====
#[derive(Serialize)]
pub struct Request {
    pub id: u64,
    pub path: String,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct FileInfo {
    pub name: String,
    #[serde(default)]
    pub file_type: String,
    pub permissions: String,
    pub absolute_path: String,
    pub modified: String,
    pub size: u64,
}

// FileEntry 用于 cache 和 API 响应
#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct FileEntry {
    pub name: String,
    pub is_dir: bool,
    #[serde(default)]
    pub file_type: String,
    pub size: u64,
    pub permissions: String,
    pub modified: String,
}

#[derive(Deserialize, Debug, Clone)]
pub struct Response {
    pub id: u64,
    pub path: String,
    pub data: Vec<HashMap<String, Vec<FileInfo>>>,
}

// ===== Cache 管理 =====
const CACHE_FILE_BASENAME: &str = "cache.json";

pub type CacheData = HashMap<String, Vec<FileEntry>>;

fn cache_dir() -> PathBuf {
    if let Ok(home) = std::env::var("HOME") {
        PathBuf::from(home).join(".lazysync").join("cache")
    } else {
        PathBuf::from(".lazysync").join("cache")
    }
}

fn clear_cache_dir(dir: &Path) -> std::io::Result<()> {
    if dir.exists() {
        for entry in fs::read_dir(dir)? {
            let entry = entry?;
            let path = entry.path();
            if path.is_file() {
                fs::remove_file(path)?;
            }
        }
    }
    Ok(())
}

fn generate_hash() -> String {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let pid = std::process::id() as u128;
    format!("{:x}{:x}", pid, now)
}

fn init_cache_path(is_hash: bool) -> std::io::Result<PathBuf> {
    let dir = cache_dir();
    fs::create_dir_all(&dir)?;
    clear_cache_dir(&dir)?;

    let filename = if is_hash {
        format!("{}.{}", CACHE_FILE_BASENAME, generate_hash())
    } else {
        CACHE_FILE_BASENAME.to_string()
    };
    Ok(dir.join(filename))
}

pub fn load_cache(cache_path: &Path) -> CacheData {
    if cache_path.exists() {
        if let Ok(content) = fs::read_to_string(cache_path) {
            if let Ok(cache) = serde_json::from_str::<CacheData>(&content) {
                return cache;
            }
        }
    }
    HashMap::new()
}

pub fn save_cache(cache: &CacheData, cache_path: &Path) -> std::io::Result<()> {
    let content = serde_json::to_string_pretty(cache)?;
    fs::write(cache_path, content)?;
    Ok(())
}

pub fn update_cache_with_response(resp: &Response, cache_path: &Path) -> std::io::Result<()> {
    let mut cache = load_cache(cache_path);

    for dir_map in &resp.data {
        for (abs_path, entries) in dir_map {
            let file_entries: Vec<FileEntry> = entries.iter().map(|fi| {
                let is_dir = fi.permissions.chars().next() == Some('d');
                normalize_entry(FileEntry {
                    name: fi.name.clone(),
                    is_dir,
                    file_type: infer_file_type(&fi.file_type, &fi.permissions, is_dir),
                    size: fi.size,
                    permissions: fi.permissions.clone(),
                    modified: fi.modified.clone(),
                })
            }).collect();
            cache.insert(abs_path.clone(), file_entries);
        }
    }

    save_cache(&cache, cache_path)
}

// 规范化路径：去掉末尾的 /（除非是根路径 /）
fn normalize_path(path: &str) -> String {
    let trimmed = path.trim();
    if trimmed == "/" || trimmed.is_empty() {
        trimmed.to_string()
    } else {
        trimmed.trim_end_matches('/').to_string()
    }
}

fn infer_file_type(file_type: &str, permissions: &str, is_dir: bool) -> String {
    if !file_type.is_empty() {
        return file_type.to_string();
    }
    if let Some(first) = permissions.chars().next() {
        if first == 'l' {
            return "symlink".to_string();
        }
        if first == 'd' {
            return "dir".to_string();
        }
    }
    if is_dir {
        "dir".to_string()
    } else {
        "file".to_string()
    }
}

fn normalize_permissions(permissions: &str, file_type: &str) -> String {
    if file_type != "symlink" {
        return permissions.to_string();
    }
    let mut chars = permissions.chars();
    let _ = chars.next();
    let rest: String = chars.collect();
    format!("l{}", rest)
}

fn normalize_entry(mut entry: FileEntry) -> FileEntry {
    entry.file_type = infer_file_type(&entry.file_type, &entry.permissions, entry.is_dir);
    entry.permissions = normalize_permissions(&entry.permissions, &entry.file_type);
    entry.is_dir = entry.file_type == "dir" || entry.permissions.chars().next() == Some('d');
    entry
}

// ===== 客户端结构 =====
pub struct Client {
    writer: Arc<Mutex<TcpStream>>,
    reader: Arc<Mutex<BufReader<TcpStream>>>,
    req_id: Arc<Mutex<u64>>,
    response_channels: Arc<Mutex<HashMap<u64, oneshot::Sender<Response>>>>,
    receiver_handle: Option<thread::JoinHandle<()>>,
    cache_path: Arc<PathBuf>,
}

impl Client {
    pub fn new(server_addr: &str) -> std::io::Result<Self> {
        Self::new_with_cache(server_addr, false)
    }

    pub fn new_with_cache(server_addr: &str, is_hash: bool) -> std::io::Result<Self> {
        let cache_path = init_cache_path(is_hash)?;
        let stream = TcpStream::connect(server_addr)?;
        stream.set_nodelay(true)?;
        
        let writer = Arc::new(Mutex::new(stream.try_clone()?));
        let reader = Arc::new(Mutex::new(BufReader::new(stream)));
        let req_id = Arc::new(Mutex::new(0u64));
        let response_channels: Arc<Mutex<HashMap<u64, oneshot::Sender<Response>>>> = 
            Arc::new(Mutex::new(HashMap::new()));
        let cache_path = Arc::new(cache_path);

        // 启动接收线程
        let response_channels_clone = Arc::clone(&response_channels);
        let reader_clone = Arc::clone(&reader);
        let cache_path_clone = Arc::clone(&cache_path);
        let receiver_handle = thread::spawn(move || {
            let reader = reader_clone;
            loop {
                let line = {
                    let mut r = reader.lock().unwrap();
                    let mut line = String::new();
                    match r.read_line(&mut line) {
                        Ok(0) => break, // EOF
                        Ok(_) => line.trim().to_string(),
                        Err(_) => break,
                    }
                };
                
                if line.is_empty() {
                    continue;
                }

                match serde_json::from_str::<Response>(&line) {
                    Ok(resp) => {
                        // 检查是否有等待的channel
                        {
                            let mut channels = response_channels_clone.lock().unwrap();
                            if let Some(sender) = channels.remove(&resp.id) {
                                let _ = sender.send(resp.clone());
                            }
                        }

                        // 更新cache
                        if let Err(e) = update_cache_with_response(&resp, cache_path_clone.as_path()) {
                            eprintln!("Failed to update cache: {}", e);
                        }
                    }
                    Err(e) => {
                        eprintln!("Failed to parse response: {}", e);
                    }
                }
            }
        });

        Ok(Self {
            writer,
            reader,
            req_id,
            response_channels,
            receiver_handle: Some(receiver_handle),
            cache_path,
        })
    }

    pub fn request_path(&self, path: &str) -> std::io::Result<()> {
        let mut id = self.req_id.lock().unwrap();
        *id += 1;
        let req = Request {
            id: *id,
            path: path.to_string(),
        };

        let mut writer = self.writer.lock().unwrap();
        writeln!(writer, "{}", serde_json::to_string(&req).unwrap())?;
        writer.flush()?;
        Ok(())
    }

    pub async fn get_path(&self, path: &str) -> Result<Vec<FileEntry>, String> {
        // 规范化路径：去掉末尾的 /
        let normalized_path = normalize_path(path);
        
        // 1. 先检查cache
        if let Some(entries) = {
            let cache = load_cache(self.cache_path.as_path());
            let normalized = normalize_path(&normalized_path);
            cache.get(&normalized).cloned()
        } {
            let normalized_entries: Vec<FileEntry> = entries
                .into_iter()
                .map(normalize_entry)
                .collect();
            return Ok(normalized_entries);
        }

        // 2. 没有cache，发送请求并等待响应
        let (tx, rx) = oneshot::channel();
        let request_id = {
            let mut id = self.req_id.lock().unwrap();
            *id += 1;
            let req_id = *id;
            
            // 注册channel
            {
                let mut channels = self.response_channels.lock().unwrap();
                channels.insert(req_id, tx);
            }

            // 发送请求（使用规范化后的路径）
            let req = Request {
                id: req_id,
                path: normalized_path.clone(),
            };

            let mut writer = self.writer.lock().map_err(|e| format!("Lock error: {}", e))?;
            writeln!(writer, "{}", serde_json::to_string(&req).unwrap())
                .map_err(|e| format!("Write error: {}", e))?;
            writer.flush().map_err(|e| format!("Flush error: {}", e))?;

            req_id
        };

        // 等待响应（最多等待5秒）
        match tokio::time::timeout(Duration::from_secs(5), rx).await {
            Ok(Ok(resp)) => {
                // 从响应数据中查找请求的路径
                let request_path_buf = std::path::PathBuf::from(&normalized_path);
                let canonical_request_path = request_path_buf.canonicalize()
                    .unwrap_or_else(|_| request_path_buf.clone())
                    .display()
                    .to_string();
                
                let mut found_entries: Vec<FileEntry> = Vec::new();
                
                for dir_map in &resp.data {
                    for (abs_path, file_infos) in dir_map {
                        let abs_path_buf = std::path::PathBuf::from(abs_path);
                        let normalized_resp_path = abs_path_buf.canonicalize()
                            .unwrap_or_else(|_| abs_path_buf.clone())
                            .display()
                            .to_string();
                        
                        // 规范化响应路径用于比较
                        let normalized_abs_path = normalize_path(abs_path);
                        
                        if abs_path == &normalized_path 
                            || normalized_abs_path == normalized_path
                            || abs_path == &canonical_request_path 
                            || normalized_resp_path == canonical_request_path 
                            || normalized_resp_path == normalized_path {
                            found_entries = file_infos.iter().map(|fi| {
                                let is_dir = fi.permissions.chars().next() == Some('d');
                                normalize_entry(FileEntry {
                                    name: fi.name.clone(),
                                    is_dir,
                                    file_type: infer_file_type(&fi.file_type, &fi.permissions, is_dir),
                                    size: fi.size,
                                    permissions: fi.permissions.clone(),
                                    modified: fi.modified.clone(),
                                })
                            }).collect();
                            break;
                        }
                    }
                    if !found_entries.is_empty() {
                        break;
                    }
                }
                
                Ok(found_entries)
            }
            Ok(Err(_)) => {
                let mut channels = self.response_channels.lock().unwrap();
                channels.remove(&request_id);
                Err("Channel error".to_string())
            }
            Err(_) => {
                let mut channels = self.response_channels.lock().unwrap();
                channels.remove(&request_id);
                Err("Timeout waiting for response".to_string())
            }
        }
    }
}

impl Drop for Client {
    fn drop(&mut self) {
        // 清理资源
        if let Some(handle) = self.receiver_handle.take() {
            // 注意：这里无法优雅地停止接收线程，因为它在等待读取
            // 在实际应用中，可能需要添加关闭标志
            drop(handle);
        }
    }
}

// ===== Python 绑定 =====
#[cfg(feature = "python")]
use pyo3::prelude::*;
#[cfg(feature = "python")]
use pyo3::types::PyDict;

#[cfg(feature = "python")]
#[pyclass]
pub struct PyClient {
    client: Client,
    rt: tokio::runtime::Runtime,
}

#[cfg(feature = "python")]
#[pymethods]
impl PyClient {
    #[new]
    fn new(server_addr: &str, is_hash: Option<bool>) -> PyResult<Self> {
        let rt = tokio::runtime::Runtime::new()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                format!("Failed to create runtime: {}", e)
            ))?;
        
        let client = Client::new_with_cache(server_addr, is_hash.unwrap_or(false))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(
                format!("Failed to connect to server: {}", e)
            ))?;

        Ok(Self { client, rt })
    }

    fn request_path(&self, path: &str) -> PyResult<()> {
        self.client.request_path(path)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(
                format!("Failed to request path: {}", e)
            ))
    }

    fn get_path(&self, path: &str) -> PyResult<Vec<PyObject>> {
        let entries = self.rt.block_on(self.client.get_path(path))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e))?;
        
        Python::with_gil(|py| {
            entries.iter().map(|entry| {
                let dict = PyDict::new(py);
                dict.set_item("name", entry.name.clone())?;
                dict.set_item("is_dir", entry.is_dir)?;
                dict.set_item("type", entry.file_type.clone())?;
                dict.set_item("size", entry.size)?;
                dict.set_item("permissions", entry.permissions.clone())?;
                dict.set_item("modified", entry.modified.clone())?;
                Ok(dict.to_object(py))
            }).collect()
        })
    }
}

#[cfg(feature = "python")]
#[pymodule]
fn rfb_client(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<PyClient>()?;
    Ok(())
}
