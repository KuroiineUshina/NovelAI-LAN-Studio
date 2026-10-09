export type Tab = "generate" | "gallery" | "presets" | "stats" | "settings";
export type GenerationMode = "txt2img" | "img2img" | "inpaint" | "upscale" | "director";
export type DirectorTool = "bg-removal" | "lineart" | "sketch" | "colorize" | "emotion" | "declutter" | "declutter-keep-bubbles";
export type ReferenceKind = "character" | "style" | "character&style";

export interface VibeReference {
  asset_id: string;
  strength: number;
  information_extracted: number;
}

export interface CharacterReference {
  asset_id: string;
  kind: ReferenceKind;
  strength: number;
  fidelity: number;
}

export interface DirectorInput {
  tool: DirectorTool;
  emotion: string;
  prompt: string;
  level: number;
}
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";

export interface ModelSpec {
  id: string;
  label: string;
  family: string;
  max_characters: number;
  supports_vibe_transfer?: boolean;
  supports_character_reference?: boolean;
}

export interface AppStatus {
  name: string;
  version: string;
  server: string;
  lan_enabled: boolean;
  tailscale_enabled: boolean;
  remote_access_supported: boolean;
  lan_urls: string[];
  tailscale_urls: string[];
  mobile_urls: string[];
  admin_available: boolean;
  device_approval_required: boolean;
  device_authorized: boolean;
  device_name: string | null;
  pending_device_count: number;
  pending_api_profile_transfer_count: number;
  has_token: boolean;
  models: ModelSpec[];
  security_notice: string;
}

export interface DeviceApproval {
  device_id: string;
  display_name: string;
  status: "pending" | "approved" | "denied" | "revoked" | "expired";
  requested_at: string;
  decided_at: string | null;
  approved_at: string | null;
  last_seen_at: string | null;
  last_address: string | null;
  user_agent: string;
}

export interface ApiProfileTransferRequest {
  id: string;
  device_id: string;
  display_name: string;
  last_address: string | null;
  profile_name: string;
  key_id: string;
  verification_code: string;
  status: "pending" | "approved" | "denied" | "expired";
  requested_at: string;
  decided_at: string | null;
  delivered_at: string | null;
}

export interface AnlasStatus {
  available: boolean;
  active: boolean;
  tier: number;
  tier_name: string;
  subscription_anlas: number | null;
  paid_anlas: number | null;
  remaining_anlas: number | null;
  usage_percent: number | null;
  usage_is_negative: boolean | null;
  usage_time_until_next_percent: number | null;
  refreshed_at: string | null;
}

export interface CharacterPreset {
  id: string;
  name: string;
  tag_id: string;
  tag_name: string;
  subject_type: "girl" | "boy" | "other";
  prompt: string;
  negative_prompt: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface CharacterSetMember {
  id: string;
  name: string;
  tag_id: string;
  tag_name: string;
  position: number;
}

export interface CharacterSet {
  id: string;
  name: string;
  preset_ids: string[];
  members: CharacterSetMember[];
  created_at: string;
  updated_at: string;
}

export interface DiscordWebhookTarget {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  configured?: boolean;
}

export type ClaudeIntegrationState =
  | "ready"
  | "mcp_missing"
  | "skill_missing"
  | "skill_outdated";

export interface ClaudeIntegrationStatus {
  state: ClaudeIntegrationState;
  message: string;
  mcp_url: string;
  mcp_registered: boolean;
  mcp_server_name: string | null;
  register_command: string;
  skill_name: string;
  skill_installed: boolean;
  skill_up_to_date: boolean;
  last_mcp_activity_at: string | null;
  last_checked_at: string;
}

export interface QualityPromptPreset {
  id: string;
  name: string;
  prompt: string;
  /** Empty when the preset does not carry a quality negative. */
  negative_prompt: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface ImageTag {
  id: string;
  name: string;
  count?: number;
}

export interface ImageRecord {
  id: string;
  job_id: string;
  parent_image_id: string | null;
  mime_type: string;
  width: number;
  height: number;
  mode: GenerationMode;
  model: string;
  prompt: string;
  quality_prompt: string;
  description_prompt: string;
  quality_negative_prompt: string;
  description_negative_prompt: string;
  negative_prompt: string;
  settings: GenerationParameters & { nsfw_enabled?: boolean; nsfw_prompt?: string };
  character_snapshot: Array<Record<string, unknown>>;
  seed: number | null;
  created_at: string;
  expires_at: string | null;
  favorite_at: string | null;
  tags: ImageTag[];
  content_url: string;
  thumbnail_url: string;
  download_url: string;
}

export interface UploadAsset {
  id: string;
  original_name: string;
  mime_type: string;
  width: number;
  height: number;
  created_at: string;
  expires_at: string;
  content_url: string;
  thumbnail_url: string;
  kind: "upload";
}

export interface GenerationParameters {
  width: number;
  height: number;
  steps: number;
  guidance: number;
  guidance_rescale: number;
  sampler: string;
  noise_schedule: NoiseSchedule;
  quality: boolean;
  count: number;
  seed: number | null;
  strength: number;
  noise: number;
}

export type NoiseSchedule = "karras" | "exponential" | "polyexponential";

export const DEFAULT_GENERATION_PARAMETERS: GenerationParameters = {
  width: 1024,
  height: 1024,
  steps: 28,
  guidance: 5,
  guidance_rescale: 0,
  sampler: "k_dpmpp_2m",
  noise_schedule: "karras",
  quality: true,
  count: 1,
  seed: null,
  strength: 0.7,
  noise: 0.2,
};

export interface GenerationRequest {
  mode: GenerationMode;
  repeat_count?: number;
  model: string;
  quality_prompt: string;
  description_prompt: string;
  quality_negative_prompt: string;
  description_negative_prompt: string;
  nsfw_enabled: boolean;
  nsfw_prompt?: string;
  character_preset_ids: string[];
  source_asset_id: string | null;
  mask_asset_id: string | null;
  vibe_references?: VibeReference[];
  character_references?: CharacterReference[];
  director?: DirectorInput | null;
  parameters: GenerationParameters;
}

export interface Job {
  id: string;
  mode: GenerationMode;
  status: JobStatus;
  queue_position: number | null;
  error_code: string | null;
  error_message: string | null;
  correlation_id: string;
  output_count: number;
  completed_requests?: number;
  cancel_requested?: boolean | number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  request: GenerationRequest & { character_snapshot?: Array<Record<string, unknown>> };
}

export interface Statistics {
  lifetime: number;
  today: number;
  last_7_days: number;
  temporary: number;
  favorites: number;
  daily: Array<{ date: string; count: number }>;
}

export interface GenerationDraft {
  schema_version: number;
  quality_prompt: string;
  description_prompt: string;
  quality_preset_id: string | null;
  quality_negative_prompt: string;
  description_negative_prompt: string;
  nsfw_enabled: boolean;
  nsfw_prompt: string;
  character_preset_ids: string[];
  model: string;
  parameters: GenerationParameters;
}

export interface GenerationDraftSyncEnvelope {
  revision: number;
  source_client_id: string | null;
  draft: GenerationDraft;
}

export interface ImageReuseOptions {
  quality_prompt: boolean;
  description_prompt: boolean;
  quality_negative_prompt: boolean;
  description_negative_prompt: boolean;
  nsfw_enabled: boolean;
  character_presets: boolean;
  model: boolean;
  dimensions: boolean;
  steps: boolean;
  guidance: boolean;
  guidance_rescale: boolean;
  sampler: boolean;
  quality: boolean;
  seed: boolean;
  count: boolean;
  strength_noise: boolean;
}
