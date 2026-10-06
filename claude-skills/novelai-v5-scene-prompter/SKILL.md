---
name: novelai-v5-scene-prompter
description: Read NovelAI LAN Studio's current model, selected characters, and shared draft through MCP, then write compact NovelAI V5 scene-level positive and negative prompts, edit the quality prompt (artist mix, style, quality tags) when explicitly asked, and optionally apply an explicitly requested NSFW state. Use when the user mentions NovelAI LAN Studio or asks to compose, compress, insert, or apply a scene or quality prompt; never alter permanent character identity prompts.
---

# NovelAI LAN Studio Scene Prompter

Use the `novelaiLANStudio` MCP server instead of Computer Use or browser automation.

In Claude Code the tools appear as `mcp__novelaiLANStudio__<tool>` (for example `mcp__novelaiLANStudio__get_prompt_context`). If they are not loaded, load them with ToolSearch before calling. The server runs only while NovelAI LAN Studio is open on this PC (http://127.0.0.1:8787/mcp/); if it is unreachable, tell the user to start Studio instead of working around it.

## Workflow

1. Call `get_prompt_context` before composing anything.
2. Use its model, current prompts, selected quality preset, character order, subject types, and character prompts as the only Studio context.
3. Write scene-level positive and negative descriptions according to the rules below.
4. If the user explicitly asks to write, insert, apply, or put one result into Studio, call `apply_description_prompts` with the exact `revision` returned by step 1. Pass `nsfw_enabled` only when the user explicitly asks to change that state; otherwise omit it.
5. Only when the user explicitly asks to change the quality prompt (artist tags, style, quality tags, quality negative), call `apply_quality_prompts` with the latest `revision`. Omit the side you are not changing. A description write increments the revision, so re-read context between the two writes.
6. If any write returns `revision_conflict`, stop and tell the user the shared draft changed. Do not silently read again and overwrite newer work.
7. A shared draft holds one variant. Do not apply the next variant until the user has generated the current one or explicitly asks to skip it.
8. Report the applied prompts briefly. Do not start NovelAI image generation.

If the user only asks for a suggestion or preview, return the prompts without calling a write tool.

## Prompt boundaries

- Preserve permanent character identity prompts. Do not copy or rewrite appearance, body, species, hair, eyes, tattoos, ears, tails, or other preset identity definitions into the scene prompt.
- Put scene, action, interaction, pose, expression, composition, camera, environment, lighting, and scene-specific clothing in the positive description.
- Put likely failure states and explicitly unwanted scene elements in the negative description. Never copy quality-negative tags into it.
- "묘사만" means description only: leave the quality prompt untouched.
- Preserve the NSFW setting unless the user explicitly asks to change it.
- Never request or expose NovelAI tokens, Discord webhooks, images, credentials, storage settings, or unrelated local data.
- Use only `get_prompt_context`, `apply_description_prompts`, and `apply_quality_prompts`. Do not call generation, deletion, export, webhook, shell, filesystem, browser, or Computer Use tools.

## Quality prompt edits

- Keep the existing artist combination and weights; add, remove, or reweight only the tags the user asked about. Never replace the whole quality prompt unless the user asks for a new one.
- Use NovelAI weighting syntax already in use: `1.2::artist:name::` (values below 1 weaken), one artist per weight group.
- Keep `year`, `meta:`, and quality tags such as `very aesthetic, masterpiece` in the quality prompt, not in the description.
- Do not tighten the quality negative aggressively; remove duplicates only when asked.
- Applying does not overwrite a saved quality preset. If the result reports `differs_from_preset`, tell the user they can press 덮어쓰기 in Studio to update that preset.

## Character handling

- Respect the selected character order and subject types.
- Add compact subject-count tags such as `1girl, 1boy` when useful for separation.
- Describe per-character actions by order or display name without moving permanent appearance into the scene prompt.
- State shared clothing or actions globally, then add only necessary per-character distinctions.

## Prompt style

- Accept Korean scene instructions.
- Return compact comma-separated prompts, primarily in natural Korean.
- Keep well-recognized NovelAI tags in English when translation would reduce reliability, including subject counts, common clothing tags, camera tags, and composition tags.
- Remove repetition, filler, contradictions, and synonymous tags.
- Do not add quality tags, `masterpiece`, `nsfw`, or `uncensored` to the description; Studio handles those separately.
