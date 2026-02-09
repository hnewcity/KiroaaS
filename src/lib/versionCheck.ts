import { platform, arch, version } from '@tauri-apps/api/os';
import { VERSION_CHECK_API } from './config';
import type { AppConfig } from './config';
import { getAppVersion, getDeviceModel } from './tauri';

export type UpdateTrigger = 'manual' | 'app_start' | 'app_close' | 'scheduled';

export interface UpdateInfo {
  hasUpdate: boolean;
  latestVersion?: string;
  currentVersion?: string;
  downloadUrl?: string;
  changelog?: Array<{ version: string; changes: string[] }>;
}

export async function checkVersionUpdate(
  config: AppConfig,
  trigger: UpdateTrigger,
): Promise<UpdateInfo | null> {
  try {
    const clientId = config.client_id || '';

    const [appVersion, currentPlatform, currentArch, osVersion, deviceModel] = await Promise.all([
      getAppVersion(),
      platform(),
      arch(),
      version(),
      getDeviceModel(),
    ]);

    const requestBody = {
      currentVersion: appVersion,
      platform: currentPlatform,
      arch: currentArch,
      osVersion,
      deviceModel,
      clientId,
      trigger,
    };
    console.log('[CheckUpdate] Request:', VERSION_CHECK_API, requestBody);

    const response = await fetch(VERSION_CHECK_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    });
    const data: UpdateInfo = await response.json();
    console.log('[CheckUpdate] Response:', response.status, data);
    return data;
  } catch (err) {
    console.error('[CheckUpdate] Failed:', err);
    return null;
  }
}
