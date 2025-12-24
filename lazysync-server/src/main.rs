use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    fs,
    io::{BufRead, BufReader, Write},
    net::{TcpListener, TcpStream},
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
    thread,
    time::SystemTime,
};

#[derive(Serialize, Clone)]
struct FileInfo {
    name: String,
    file_type: String,
    permissions: String,
    absolute_path: String,
    modified: String,
    size: u64,
}

#[derive(Serialize)]
struct Response {
    id: u64,
    path: String,
    data: Vec<HashMap<String, Vec<FileInfo>>>,
}

#[derive(Deserialize)]
struct Request {
    id: u64,
    path: String,
}

fn format_permissions(meta: &fs::Metadata) -> String {
    let perms = meta.permissions();
    let mode = perms.mode();
    
    let mut result = String::with_capacity(10);
    
    // File type
    let file_type = meta.file_type();
    result.push(if file_type.is_symlink() {
        'l'
    } else if meta.is_dir() {
        'd'
    } else {
        '-'
    });
    
    // Owner permissions
    result.push(if mode & 0o400 != 0 { 'r' } else { '-' });
    result.push(if mode & 0o200 != 0 { 'w' } else { '-' });
    result.push(if mode & 0o100 != 0 { 'x' } else { '-' });
    
    // Group permissions
    result.push(if mode & 0o040 != 0 { 'r' } else { '-' });
    result.push(if mode & 0o020 != 0 { 'w' } else { '-' });
    result.push(if mode & 0o010 != 0 { 'x' } else { '-' });
    
    // Other permissions
    result.push(if mode & 0o004 != 0 { 'r' } else { '-' });
    result.push(if mode & 0o002 != 0 { 'w' } else { '-' });
    result.push(if mode & 0o001 != 0 { 'x' } else { '-' });
    
    result
}

fn format_modified_time(meta: &fs::Metadata) -> String {
    if let Ok(modified) = meta.modified() {
        match modified.duration_since(SystemTime::UNIX_EPOCH) {
            Ok(duration) => {
                let secs = duration.as_secs();
                // 使用chrono格式化日期时间
                if let Some(dt) = chrono::DateTime::from_timestamp(secs as i64, 0) {
                    let local_dt = dt.with_timezone(&chrono::Local);
                    local_dt.format("%Y-%m-%d %H:%M:%S").to_string()
                } else {
                    format!("{}", secs)
                }
            }
            Err(_) => "N/A".to_string(),
        }
    } else {
        "N/A".to_string()
    }
}

fn to_absolute_path(path: &Path) -> PathBuf {
    if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .unwrap_or_else(|_| PathBuf::from("."))
            .join(path)
    }
}

fn file_type_string(meta: &fs::Metadata) -> String {
    let file_type = meta.file_type();
    if file_type.is_symlink() {
        "symlink".to_string()
    } else if meta.is_dir() {
        "dir".to_string()
    } else if meta.is_file() {
        "file".to_string()
    } else {
        "other".to_string()
    }
}

fn is_dir_or_symlink_dir(path: &Path) -> bool {
    let meta = match fs::symlink_metadata(path) {
        Ok(m) => m,
        Err(_) => return false,
    };
    if meta.is_dir() {
        return true;
    }
    if meta.file_type().is_symlink() {
        if let Ok(target_meta) = fs::metadata(path) {
            return target_meta.is_dir();
        }
    }
    false
}

fn read_dir(path: &Path) -> Option<Vec<FileInfo>> {
    let mut entries = Vec::new();
    let iter = fs::read_dir(path).ok()?;

    for e in iter.flatten() {
        if let Ok(meta) = fs::symlink_metadata(e.path()) {
            let file_path = e.path();
            let absolute_path = to_absolute_path(&file_path)
                .display()
                .to_string();
            
            entries.push(FileInfo {
                name: e.file_name().to_string_lossy().to_string(),
                file_type: file_type_string(&meta),
                permissions: format_permissions(&meta),
                absolute_path,
                modified: format_modified_time(&meta),
                size: meta.len(),
            });
        }
    }

    Some(entries)
}

fn handle_client(stream: TcpStream) {
    let peer = stream.peer_addr().ok();
    println!("client connected: {:?}", peer);

    let mut writer = stream.try_clone().unwrap();
    let reader = BufReader::new(stream);

    for line in reader.lines().flatten() {
        let req: Request = match serde_json::from_str(&line) {
            Ok(r) => r,
            Err(_) => continue,
        };

        let path = PathBuf::from(&req.path);
        let request_path = to_absolute_path(&path);
        let is_dir_like = is_dir_or_symlink_dir(&path);
        
        let mut data = Vec::new();
        
        // 1. 添加父目录（如果存在）
        if let Some(parent_path) = path.parent() {
            if let Some(entries) = read_dir(parent_path) {
                let parent_abs_path = to_absolute_path(parent_path)
                    .display()
                    .to_string();
                let mut parent_map = HashMap::new();
                parent_map.insert(parent_abs_path, entries);
                data.push(parent_map);
            }
        }
        
        // 2. 添加当前路径（如果是目录或链接到目录）
        if is_dir_like {
            if let Some(entries) = read_dir(&path) {
                let current_abs_path = to_absolute_path(&request_path)
                    .display()
                    .to_string();
                let mut current_map = HashMap::new();
                current_map.insert(current_abs_path.clone(), entries.clone());
                data.push(current_map);
            
                // 原始请求路径可能是相对路径，添加规范化后的别名映射
                let normalized_original_path = req.path.trim_end_matches('/').to_string();
                let normalized_original_abs = to_absolute_path(Path::new(&normalized_original_path))
                    .display()
                    .to_string();
                if normalized_original_abs != current_abs_path {
                    let mut original_map = HashMap::new();
                    original_map.insert(normalized_original_abs, entries);
                    data.push(original_map);
                }
            
                // 3. 添加子目录（当前路径的子目录，以及链接到目录的子项）
                if let Ok(iter) = std::fs::read_dir(&path) {
                    for entry in iter.flatten() {
                        let child_path = entry.path();
                        if is_dir_or_symlink_dir(&child_path) {
                            if let Some(child_entries) = read_dir(&child_path) {
                                let child_abs_path = to_absolute_path(&child_path)
                                    .display()
                                    .to_string();
                                let mut child_map = HashMap::new();
                                child_map.insert(child_abs_path, child_entries);
                                data.push(child_map);
                            }
                        }
                    }
                }
            }
        }

        let resp = Response {
            id: req.id,
            path: req.path,
            data,
        };

        let json = serde_json::to_string(&resp).unwrap();
        writeln!(writer, "{}", json).unwrap();
    }

    println!("client disconnected: {:?}", peer);
}

fn main() -> std::io::Result<()> {
    let listener = TcpListener::bind("127.0.0.1:9000")?;
    println!("server listening on 127.0.0.1:9000");

    for stream in listener.incoming() {
        if let Ok(s) = stream {
            thread::spawn(|| handle_client(s));
        }
    }
    Ok(())
}
