use std::{
    fs::{self, File, OpenOptions},
    io,
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

use tauri::{Manager, State};

struct ApiState {
    base_url: String,
}

struct ApiProcess {
    child: Mutex<Option<Child>>,
}

impl Drop for ApiProcess {
    fn drop(&mut self) {
        if let Ok(mut guard) = self.child.lock() {
            if let Some(child) = guard.take() {
                stop_api_child(child);
            }
        }
    }
}

struct ApiLaunch {
    child: Child,
    logs_dir: PathBuf,
    python: PathBuf,
}

#[tauri::command]
fn api_base_url(state: State<ApiState>) -> String {
    state.base_url.clone()
}

fn pick_local_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|error| error.to_string())?;
    let port = listener
        .local_addr()
        .map_err(|error| error.to_string())?
        .port();
    drop(listener);
    Ok(port)
}

fn repo_root_from_current_dir() -> Result<PathBuf, String> {
    if let Ok(value) = std::env::var("ORCHESTRA_REPO_ROOT") {
        let candidate = PathBuf::from(value);
        if candidate.join("run_local_api.py").exists() {
            return Ok(candidate);
        }
    }

    let current = std::env::current_dir().map_err(|error| error.to_string())?;
    for candidate in current.ancestors() {
        if candidate.join("run_local_api.py").exists() {
            return Ok(candidate.to_path_buf());
        }
    }
    Err(format!(
        "Cannot resolve repository root from current directory: {}",
        current.display()
    ))
}

fn select_python(repo_root: &PathBuf) -> PathBuf {
    if let Ok(value) = std::env::var("ORCHESTRA_PYTHON") {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed);
        }
    }

    let candidates = [
        repo_root.join(".venv").join("Scripts").join("python.exe"),
        repo_root.join(".venv").join("bin").join("python"),
    ];
    for candidate in candidates {
        if candidate.exists() {
            return candidate;
        }
    }

    if cfg!(windows) {
        PathBuf::from("python")
    } else {
        PathBuf::from("python3")
    }
}

fn open_log_file(logs_dir: &PathBuf, name: &str) -> Result<File, String> {
    OpenOptions::new()
        .create(true)
        .append(true)
        .open(logs_dir.join(name))
        .map_err(|error| error.to_string())
}

fn spawn_api(port: u16) -> Result<ApiLaunch, String> {
    let repo_root = repo_root_from_current_dir()?;
    let script = repo_root.join("run_local_api.py");
    if !script.exists() {
        return Err(format!("Local API script not found: {}", script.display()));
    }

    let python = select_python(&repo_root);
    let logs_dir = repo_root.join("tmp").join("tauri_sidecar");
    fs::create_dir_all(&logs_dir).map_err(|error| error.to_string())?;
    let stdout = open_log_file(&logs_dir, "api_stdout.log")?;
    let stderr = open_log_file(&logs_dir, "api_stderr.log")?;

    let child = Command::new(&python)
        .arg(script)
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(port.to_string())
        .env("LOCAL_API_HOST", "127.0.0.1")
        .env("LOCAL_API_PORT", port.to_string())
        .current_dir(repo_root)
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .spawn()
        .map_err(|error| {
            format!(
                "Failed to spawn local API with {}: {error}",
                python.display()
            )
        })?;

    Ok(ApiLaunch {
        child,
        logs_dir,
        python,
    })
}

fn stop_api_child(mut child: Child) {
    let _ = child.kill();
    let _ = child.wait();
}

fn wait_for_health(port: u16, timeout: Duration) -> Result<(), String> {
    let deadline = Instant::now() + timeout;
    let mut last_error = "local API has not answered yet".to_string();

    while Instant::now() < deadline {
        match try_health(port) {
            Ok(true) => return Ok(()),
            Ok(false) => last_error = "local API returned a non-healthy response".to_string(),
            Err(error) => last_error = error,
        }
        thread::sleep(Duration::from_millis(250));
    }

    Err(format!(
        "Local API did not become healthy within {} seconds: {last_error}",
        timeout.as_secs()
    ))
}

fn try_health(port: u16) -> Result<bool, String> {
    let mut stream = TcpStream::connect(("127.0.0.1", port)).map_err(|error| error.to_string())?;
    stream
        .set_read_timeout(Some(Duration::from_secs(2)))
        .map_err(|error| error.to_string())?;
    stream
        .set_write_timeout(Some(Duration::from_secs(2)))
        .map_err(|error| error.to_string())?;
    stream
        .write_all(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .map_err(|error| error.to_string())?;

    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|error| error.to_string())?;
    Ok(
        (response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200"))
            && response.contains("\"status\":\"ok\""),
    )
}

fn main() {
    let port = pick_local_port().expect("failed to allocate a local API port");
    let base_url = format!("http://127.0.0.1:{port}");

    tauri::Builder::default()
        .manage(ApiState {
            base_url: base_url.clone(),
        })
        .manage(ApiProcess {
            child: Mutex::new(None),
        })
        .setup(move |app| {
            let mut launch =
                spawn_api(port).map_err(|error| io::Error::new(io::ErrorKind::Other, error))?;
            wait_for_health(port, Duration::from_secs(30)).map_err(|error| {
                let _ = launch.child.kill();
                io::Error::new(
                    io::ErrorKind::Other,
                    format!(
                        "{error}. Python: {}. Sidecar logs: {}",
                        launch.python.display(),
                        launch.logs_dir.display()
                    ),
                )
            })?;
            let process_state = app.state::<ApiProcess>();
            *process_state
                .child
                .lock()
                .map_err(|error| io::Error::new(io::ErrorKind::Other, error.to_string()))? =
                Some(launch.child);
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                let child = {
                    let process_state = window.state::<ApiProcess>();
                    let taken = match process_state.child.lock() {
                        Ok(mut guard) => guard.take(),
                        Err(_) => None,
                    };
                    taken
                };
                if let Some(child) = child {
                    stop_api_child(child);
                }
            }
        })
        .invoke_handler(tauri::generate_handler![api_base_url])
        .run(tauri::generate_context!())
        .expect("error while running Orchestra");
}
