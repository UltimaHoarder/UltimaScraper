# Content Library & Media Explorer

UltimaScraper features an integrated **Content Library** that allows operators to browse, filter, preview, and play back preserved media assets directly within the browser interface.

---

## Exploring Preserved Content

Navigate to **Content** in the primary navigation drawer to enter the media browser:

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Filters: [Performer: All ▼]  [Type: Videos ▼]  [Sort: Newest ▼]   [🔍 Search...] │
├──────────────────────────────────────────────────────────────────────────────────┤
│ ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│ │ [ Video 4K ] │  │ [ Photo HD ] │  │ [ Photo HD ] │  │ [ Video MP4] │           │
│ │              │  │              │  │              │  │              │           │
│ │ @alice       │  │ @alice       │  │ @bob         │  │ @carol       │           │
│ │ "Beach day"  │  │ "Morning..." │  │ "Backstage"  │  │ "Vlog #12"   │           │
│ │ 2026-10-24   │  │ 2026-10-23   │  │ 2026-10-22   │  │ 2026-10-21   │           │
│ └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘           │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Filtering & Search Controls

- **Performer Filter**: Restrict the view to one or more specific creators.
- **Media Type Toggles**: Filter by **Photos**, **Videos**, **Audio Clips**, or **Text Posts**.
- **Full-Text Caption Search**: Search through post bodies, message text, and image metadata.
- **Date Range Picker**: Locate media captured within specific historical windows.

---

## Content Cards & Media Lightbox

Clicking any content card reveals comprehensive metadata and opens the high-resolution lightbox:

- **Original Post Context**: View the post caption, creation timestamp, like counts, and comments count.
- **File Details**: Displays the local filesystem path, file size, MIME type, resolution, and SHA256 checksum.
- **Direct Actions**:
  - **Open Local Directory**: Shows the exact storage directory on disk.
  - **Re-download / Verify**: Re-verifies file checksum against the database record.
  - **Copy Link**: Shares an internal media preview URL.

---

## Protected Media & Widevine DRM Decryption

Certain premium platforms distribute video content encrypted with **Widevine Content Decryption Modules (DRM)**:

1. **Automated Decryption**: During scrape jobs, if a stream is encrypted (CENC / Widevine), workers extract the PSSH header, request licensing keys from the platform, and automatically decrypt video and audio streams using `ffmpeg` and decryption binaries.
2. **Device Registration**:
   - Navigate to **Settings → DRM Devices**.
   - Upload your Widevine Content Decryption Module files (`client_id.bin` and `private_key.pem`).
   - The backend validates the CDM version and assigns it to download workers automatically.

---

## Filesystem Storage Layout

Media files are organized deterministically across your configured storage drives:

```
{USR_STORAGE_PATH}/
└── {site}/
    └── {performer_username}/
        ├── Posts/
        │   ├── Images/
        │   │   └── 2026-10-24_102938475_photo_01.jpg
        │   └── Videos/
        │       └── 2026-10-24_102938476_video_01.mp4
        ├── Messages/
        │   └── 2026-10-20_983746281_attachment.mp4
        └── Stories/
            └── 2026-10-24_109283746_story.jpg
```
