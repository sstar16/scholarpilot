// OS keychain 包装：Win Credential Manager / macOS Keychain / Linux Secret Service。
// 用于持有 access_token / refresh_token / BYOK API keys。
use keyring::Entry;
use serde::Serialize;

const SERVICE: &str = "scholarpilot";

#[derive(Debug, Serialize)]
pub struct SecureStorageError {
    message: String,
}

impl From<keyring::Error> for SecureStorageError {
    fn from(err: keyring::Error) -> Self {
        Self { message: err.to_string() }
    }
}

#[tauri::command]
pub fn secure_set(key: String, value: String) -> Result<(), SecureStorageError> {
    let entry = Entry::new(SERVICE, &key)?;
    entry.set_password(&value)?;
    Ok(())
}

#[tauri::command]
pub fn secure_get(key: String) -> Result<Option<String>, SecureStorageError> {
    let entry = Entry::new(SERVICE, &key)?;
    match entry.get_password() {
        Ok(v) => Ok(Some(v)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(e) => Err(e.into()),
    }
}

#[tauri::command]
pub fn secure_delete(key: String) -> Result<(), SecureStorageError> {
    let entry = Entry::new(SERVICE, &key)?;
    match entry.delete_password() {
        Ok(_) => Ok(()),
        Err(keyring::Error::NoEntry) => Ok(()), // 已不存在视为成功
        Err(e) => Err(e.into()),
    }
}
