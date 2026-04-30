use std::{
    io,
    net::TcpListener,
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
};

use tauri::{Manager, State};

struct ApiState {
    base_url: String,
}

struct ApiProcess {
    child: Mutex<Option<Child>>,
}

#[tauri::command]
fn api_base_url(state: State<ApiState>) -> String {
    state.base_url.clone()
}

fn pick_local_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|error| error.to_string())?;
    let port = listener.local_addr().map_err(|error| error.to_string())?.port();
    drop(listener);
    Ok(port)
}

fn repo_root_from_current_dir() -> Result<PathBuf, String> {
    let current = std::env::current_dir().map_err(|error| error.to_string())?;
    if current.file_name().and_then(|name| name.to_str()) == Some("src-tauri") {
        return current
            .parent()
            .and_then(|ux| ux.parent())
            .map(PathBuf::from)
            .ok_or_else(|| "Cannot resolve repository root from src-tauri.".to_string());
    }
    if current.file_name().and_then(|name| name.to_str()) == Some("ux") {
        return current
            .parent()
            .map(PathBuf::from)
            .ok_or_else(|| "Cannot resolve repository root from ux.".to_string());
    }
    Ok(current)
}

fn spawn_api(port: u16) -> Result<Child, String> {
    let repo_root = repo_root_from_current_dir()?;
    let script = repo_root.join("run_local_api.py");
    if !script.exists() {
        return Err(format!("Local API script not found: {}", script.display()));
    }
    Command::new("python")
        .arg(script)
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(port.to_string())
        .current_dir(repo_root)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| error.to_string())
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
            let child = spawn_api(port).map_err(|error| io::Error::new(io::ErrorKind::Other, error))?;
            let process_state = app.state::<ApiProcess>();
            *process_state
                .child
                .lock()
                .map_err(|error| io::Error::new(io::ErrorKind::Other, error.to_string()))? = Some(child);
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                let process_state = window.state::<ApiProcess>();
                if let Ok(mut guard) = process_state.child.lock() {
                    if let Some(mut child) = guard.take() {
                        let _ = child.kill();
                    }
                }
            }
        })
        .invoke_handler(tauri::generate_handler![api_base_url])
        .run(tauri::generate_context!())
        .expect("error while running Orchestra");
}
