export interface VirtualRuntimeApiConfig {
  baseUrl: string;
}

export interface VirtualAvatarProfile {
  id: string;
  name: string;
  description?: string;
  previewImageUrl?: string;
  vrmUrl?: string;
}

/**
 * 构造数字人运行时接口地址。
 */
export function buildVirtualApiUrl(config: VirtualRuntimeApiConfig, pathname: string): string {
  const normalizedBaseUrl = config.baseUrl.replace(/\/+$/, "");
  const normalizedPath = pathname.startsWith("/") ? pathname : `/${pathname}`;
  return `${normalizedBaseUrl}${normalizedPath}`;
}

/**
 * 预留角色档案查询接口的返回结构约束。
 */
export interface VirtualAvatarProfileResponse {
  items: VirtualAvatarProfile[];
}
