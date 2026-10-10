use std::{ffi::c_void, mem::size_of};
use windows_sys::Win32::Graphics::Dwm::{
    DwmSetWindowAttribute, DWMWA_BORDER_COLOR, DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR,
};

/// Match the native Windows title bar to the #111111 app shell in App.tsx.
pub fn apply(window: &tauri::Window) -> Result<(), String> {
    let hwnd = window.hwnd().map_err(|error| error.to_string())?;
    let background: u32 = 0x00111111;
    let foreground: u32 = 0x00ffffff;

    for (attribute, color) in [
        (DWMWA_CAPTION_COLOR, background),
        (DWMWA_TEXT_COLOR, foreground),
        (DWMWA_BORDER_COLOR, background),
    ] {
        // SAFETY: hwnd belongs to a live Tauri window, and color is a COLORREF-sized
        // value that remains valid for the duration of this synchronous call.
        let result = unsafe {
            DwmSetWindowAttribute(
                hwnd.0,
                attribute,
                &color as *const u32 as *const c_void,
                size_of::<u32>() as u32,
            )
        };
        if result < 0 {
            // Older Windows versions can reject these Windows 11 attributes;
            // the caller keeps the normal system title bar in that case.
            return Err(format!(
                "DwmSetWindowAttribute({attribute}) failed: 0x{:08X}",
                result as u32
            ));
        }
    }

    Ok(())
}
