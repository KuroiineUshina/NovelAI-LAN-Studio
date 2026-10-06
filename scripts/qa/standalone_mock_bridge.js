(() => {
  const imageUrl = "http://127.0.0.1:8879/assets/app-icon.png";
  const profiles = [
    {
      id: "profile-qa",
      name: "개인 Opus",
      server_id: "server-qa",
      server_url: "http://192.168.0.2:8787",
      created_at: Date.now(),
      active: true,
    },
  ];
  const image = {
    id: "image-qa",
    width: 1024,
    height: 1536,
    synced: false,
    favorite_at: "2026-09-02T10:02:00Z",
    thumbnail_url: imageUrl,
    content_url: imageUrl,
    settings: { nsfw_enabled: true },
    tags: [{ id: "tag-qa", name: "서윤" }],
  };
  const snapshot = {
    models: [
      { id: "nai-diffusion-5-full", label: "V5 Full" },
      { id: "nai-diffusion-4-5-full", label: "V4.5 Full" },
    ],
    presets: [
      {
        id: "preset-qa",
        name: "서윤",
        tag_id: "tag-qa",
        tag_name: "서윤",
        subject_type: "girl",
        prompt: "성인 여성, 검은 단발머리",
        negative_prompt: "어린이",
      },
    ],
    quality_presets: [
      { id: "quality-qa", name: "기본 품질", prompt: "masterpiece, best quality" },
    ],
  };
  let draft = {
    schema_version: 4,
    quality_prompt: "masterpiece, best quality",
    quality_negative_prompt: "lowres, bad anatomy",
    description_prompt: "비 오는 항구 서점, 창가에 선 성인 여성",
    description_negative_prompt: "close-up",
    nsfw_enabled: false,
    character_preset_ids: ["preset-qa"],
    model: "nai-diffusion-5-full",
    parameters: { width: 832, height: 1216, steps: 28, count: 1, guidance: 5, guidance_rescale: 0, sampler: "k_euler_ancestral" },
  };

  window.AndroidStudio = {
    bootstrap: () => JSON.stringify({ profiles, active_profile: profiles[0], snapshot, draft, pending_images: 1 }),
    listProfiles: () => JSON.stringify(profiles),
    setActiveProfile: () => true,
    renameProfile: () => true,
    deleteProfile: () => false,
    saveDraft: (raw) => { draft = JSON.parse(raw); return true; },
    listImages: (_folder, nsfwOnly) => JSON.stringify(nsfwOnly ? [image] : [image]),
    toggleFavorite: () => JSON.stringify({ ok: true }),
    downloadImage: () => true,
    refreshAccount: () => setTimeout(() => window.Standalone?.onAccountResult({ ok: true, account: { tier: 3, remaining_anlas: 9876 } }), 50),
    syncNow: () => true,
    exitStandalone: () => true,
    generate: () => setTimeout(() => window.Standalone?.onGenerationResult({ ok: true, images: [image] }), 120),
  };
})();
