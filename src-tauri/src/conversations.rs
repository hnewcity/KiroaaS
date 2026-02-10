use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use tokio::fs;

/// A single message in a conversation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConversationMessage {
    pub id: String,
    pub role: String,
    pub content: serde_json::Value,
    pub timestamp: u64,
}

/// A conversation with its messages
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Conversation {
    pub id: String,
    pub title: String,
    #[serde(rename = "createdAt")]
    pub created_at: u64,
    #[serde(rename = "updatedAt")]
    pub updated_at: u64,
    pub messages: Vec<ConversationMessage>,
    pub model: Option<String>,
}

/// Container for all conversations
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ConversationsData {
    pub conversations: Vec<Conversation>,
}

/// Get the conversations file path
fn get_conversations_path() -> Result<PathBuf, String> {
    let data_dir = dirs::data_local_dir()
        .ok_or("Failed to get local data directory")?
        .join("kiroaas");

    Ok(data_dir.join("conversations.json"))
}

/// Load conversations from disk
pub async fn load_conversations() -> Result<ConversationsData, String> {
    let path = get_conversations_path()?;

    if !path.exists() {
        return Ok(ConversationsData::default());
    }

    let content = fs::read_to_string(&path)
        .await
        .map_err(|e| format!("Failed to read conversations file: {}", e))?;

    let data: ConversationsData = serde_json::from_str(&content)
        .map_err(|e| format!("Failed to parse conversations file: {}", e))?;

    Ok(data)
}

/// Save conversations to disk (atomic write)
pub async fn save_conversations(data: &ConversationsData) -> Result<(), String> {
    let path = get_conversations_path()?;

    // Create parent directory if it doesn't exist
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .await
            .map_err(|e| format!("Failed to create conversations directory: {}", e))?;
    }

    let content = serde_json::to_string_pretty(data)
        .map_err(|e| format!("Failed to serialize conversations: {}", e))?;

    // Atomic write: write to temp file first, then rename
    let tmp_path = path.with_extension("json.tmp");
    fs::write(&tmp_path, &content)
        .await
        .map_err(|e| format!("Failed to write conversations temp file: {}", e))?;

    fs::rename(&tmp_path, &path)
        .await
        .map_err(|e| format!("Failed to rename conversations temp file: {}", e))?;

    Ok(())
}
