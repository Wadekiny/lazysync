use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
    time::SystemTime,
};

use tokio::io::{AsyncReadExt, AsyncSeekExt, AsyncWriteExt};
use tokio::sync::mpsc;
use tokio_stream::wrappers::ReceiverStream;
use tonic::{transport::Server, Request, Response, Status};

pub mod lazysync {
    tonic::include_proto!("lazysync");
}

use lazysync::{
    lazy_sync_server::{LazySync, LazySyncServer},
    DirEntries, FileInfo, GetPathRequest, GetPathResponse, HealthRequest, HealthResponse,
    ReadFileChunk, ReadFileRequest, StatRequest, StatResponse, WriteFileChunk,
    WriteFileResponse,
};

const READ_CHUNK_SIZE: usize = 64 * 1024;

fn format_permissions(meta: &fs::Metadata) -> String {
    let perms = meta.permissions();
    let mode = perms.mode();

    let mut result = String::with_capacity(10);

    let file_type = meta.file_type();
    result.push(if file_type.is_symlink() {
        'l'
    } else if meta.is_dir() {
        'd'
    } else {
        '-'
    });

    result.push(if mode & 0o400 != 0 { 'r' } else { '-' });
    result.push(if mode & 0o200 != 0 { 'w' } else { '-' });
    result.push(if mode & 0o100 != 0 { 'x' } else { '-' });
    result.push(if mode & 0o040 != 0 { 'r' } else { '-' });
    result.push(if mode & 0o020 != 0 { 'w' } else { '-' });
    result.push(if mode & 0o010 != 0 { 'x' } else { '-' });
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

fn build_file_info(path: &Path, meta: &fs::Metadata) -> FileInfo {
    let name = path
        .file_name()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_default();
    let absolute_path = to_absolute_path(path).display().to_string();

    FileInfo {
        name,
        file_type: file_type_string(meta),
        permissions: format_permissions(meta),
        absolute_path,
        modified: format_modified_time(meta),
        size: meta.len(),
    }
}

fn read_dir(path: &Path) -> Option<Vec<FileInfo>> {
    let mut entries = Vec::new();
    let iter = fs::read_dir(path).ok()?;

    for e in iter.flatten() {
        if let Ok(meta) = fs::symlink_metadata(e.path()) {
            let file_path = e.path();
            entries.push(build_file_info(&file_path, &meta));
        }
    }

    Some(entries)
}

fn build_entries_for_path(path: &str) -> Vec<DirEntries> {
    let path_buf = PathBuf::from(path);
    let request_path = to_absolute_path(&path_buf);
    let is_dir_like = is_dir_or_symlink_dir(&path_buf);
    let mut data = Vec::new();

    if let Some(parent_path) = path_buf.parent() {
        if let Some(entries) = read_dir(parent_path) {
            let parent_abs_path = to_absolute_path(parent_path).display().to_string();
            data.push(DirEntries {
                absolute_path: parent_abs_path,
                entries,
            });
        }
    }

    if is_dir_like {
        if let Some(entries) = read_dir(&path_buf) {
            let current_abs_path = to_absolute_path(&request_path).display().to_string();
            data.push(DirEntries {
                absolute_path: current_abs_path.clone(),
                entries: entries.clone(),
            });

            let normalized_original_path = path.trim_end_matches('/').to_string();
            let normalized_original_abs = to_absolute_path(Path::new(&normalized_original_path))
                .display()
                .to_string();
            if normalized_original_abs != current_abs_path {
                data.push(DirEntries {
                    absolute_path: normalized_original_abs,
                    entries: entries.clone(),
                });
            }

            if let Ok(iter) = fs::read_dir(&path_buf) {
                for entry in iter.flatten() {
                    let child_path = entry.path();
                    if is_dir_or_symlink_dir(&child_path) {
                        if let Some(child_entries) = read_dir(&child_path) {
                            let child_abs_path =
                                to_absolute_path(&child_path).display().to_string();
                            data.push(DirEntries {
                                absolute_path: child_abs_path,
                                entries: child_entries,
                            });
                        }
                    }
                }
            }
        }
    }

    data
}

#[derive(Default)]
struct LazySyncService;

#[tonic::async_trait]
impl LazySync for LazySyncService {
    async fn health(
        &self,
        _request: Request<HealthRequest>,
    ) -> Result<Response<HealthResponse>, Status> {
        Ok(Response::new(HealthResponse {
            status: "ok".to_string(),
        }))
    }

    async fn get_path(
        &self,
        request: Request<GetPathRequest>,
    ) -> Result<Response<GetPathResponse>, Status> {
        let req = request.into_inner();
        if req.path.is_empty() {
            return Err(Status::invalid_argument("path is required"));
        }

        let entries = build_entries_for_path(&req.path);
        let reply = GetPathResponse {
            path: req.path,
            entries,
        };
        Ok(Response::new(reply))
    }

    async fn stat(
        &self,
        request: Request<StatRequest>,
    ) -> Result<Response<StatResponse>, Status> {
        let req = request.into_inner();
        if req.path.is_empty() {
            return Err(Status::invalid_argument("path is required"));
        }

        let path = PathBuf::from(&req.path);
        match fs::symlink_metadata(&path) {
            Ok(meta) => Ok(Response::new(StatResponse {
                exists: true,
                info: Some(build_file_info(&path, &meta)),
            })),
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(Response::new(
                StatResponse {
                    exists: false,
                    info: None,
                },
            )),
            Err(err) => Err(Status::internal(format!("stat failed: {}", err))),
        }
    }

    type ReadFileStream = ReceiverStream<Result<ReadFileChunk, Status>>;

    async fn read_file(
        &self,
        request: Request<ReadFileRequest>,
    ) -> Result<Response<Self::ReadFileStream>, Status> {
        let req = request.into_inner();
        if req.path.is_empty() {
            return Err(Status::invalid_argument("path is required"));
        }

        let (tx, rx) = mpsc::channel(8);
        let path = req.path.clone();
        let offset = req.offset;
        let length = req.length;

        tokio::spawn(async move {
            let mut file = match tokio::fs::File::open(&path).await {
                Ok(f) => f,
                Err(err) => {
                    let _ = tx
                        .send(Err(Status::not_found(format!(
                            "open file failed: {}",
                            err
                        ))))
                        .await;
                    return;
                }
            };

            if let Err(err) = file.seek(std::io::SeekFrom::Start(offset)).await {
                let _ = tx
                    .send(Err(Status::internal(format!(
                        "seek failed: {}",
                        err
                    ))))
                    .await;
                return;
            }

            let mut remaining = if length == 0 { None } else { Some(length) };
            let mut current_offset = offset;
            let mut buffer = vec![0u8; READ_CHUNK_SIZE];

            loop {
                let read_len = match remaining {
                    Some(left) => {
                        if left == 0 {
                            let _ = tx
                                .send(Ok(ReadFileChunk {
                                    data: Vec::new(),
                                    offset: current_offset,
                                    eof: true,
                                }))
                                .await;
                            break;
                        }
                        std::cmp::min(left as usize, buffer.len())
                    }
                    None => buffer.len(),
                };

                let bytes_read = match file.read(&mut buffer[..read_len]).await {
                    Ok(0) => {
                        let _ = tx
                            .send(Ok(ReadFileChunk {
                                data: Vec::new(),
                                offset: current_offset,
                                eof: true,
                            }))
                            .await;
                        break;
                    }
                    Ok(n) => n,
                    Err(err) => {
                        let _ = tx
                            .send(Err(Status::internal(format!(
                                "read failed: {}",
                                err
                            ))))
                            .await;
                        break;
                    }
                };

                let chunk = ReadFileChunk {
                    data: buffer[..bytes_read].to_vec(),
                    offset: current_offset,
                    eof: false,
                };
                if tx.send(Ok(chunk)).await.is_err() {
                    break;
                }

                current_offset += bytes_read as u64;
                if let Some(left) = remaining.as_mut() {
                    *left -= bytes_read as u64;
                }
            }
        });

        Ok(Response::new(ReceiverStream::new(rx)))
    }

    async fn write_file(
        &self,
        request: Request<tonic::Streaming<WriteFileChunk>>,
    ) -> Result<Response<WriteFileResponse>, Status> {
        let mut stream = request.into_inner();
        let mut path: Option<String> = None;
        let mut file: Option<tokio::fs::File> = None;
        let mut bytes_written = 0u64;

        while let Some(chunk) = stream.message().await? {
            let chunk_path = if !chunk.path.is_empty() {
                Some(chunk.path.clone())
            } else {
                path.clone()
            };

            if path.is_none() {
                path = chunk_path;
            }

            let target_path = match &path {
                Some(p) if !p.is_empty() => p.clone(),
                _ => return Err(Status::invalid_argument("path is required")),
            };

            if file.is_none() {
                let opened = tokio::fs::OpenOptions::new()
                    .create(true)
                    .write(true)
                    .open(&target_path)
                    .await
                    .map_err(|err| Status::internal(format!("open file failed: {}", err)))?;
                file = Some(opened);
            }

            if let Some(f) = file.as_mut() {
                f.seek(std::io::SeekFrom::Start(chunk.offset))
                    .await
                    .map_err(|err| Status::internal(format!("seek failed: {}", err)))?;
                f.write_all(&chunk.data)
                    .await
                    .map_err(|err| Status::internal(format!("write failed: {}", err)))?;
                bytes_written += chunk.data.len() as u64;
            }

            if chunk.eof {
                break;
            }
        }

        Ok(Response::new(WriteFileResponse { bytes_written }))
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let addr = "127.0.0.1:9000".parse()?;
    println!("gRPC server listening on {}", addr);
    Server::builder()
        .add_service(LazySyncServer::new(LazySyncService::default()))
        .serve(addr)
        .await?;
    Ok(())
}
