# Referensi parameter REST API

Referensi ini dibuat dari OpenAPI pada kode repository. Bentuk request bergantung pada method dan endpoint; POST tidak selalu berarti body JSON.

Gunakan header `X-API-Key` untuk endpoint eksternal. Parameter `key` dapat dipakai sebagai alternatif autentikasi pada sebagian endpoint, tetapi pada `/api/newsletter/info-by-invite` field tersebut berisi kode undangan channel. Gunakan header untuk menghindari ambiguitas.

[Kembali ke README](../README.md) · [Swagger produksi](https://utusan.chat/docs)

## GET `/api/status`

External API: Check Bot Status using x-api-key header

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/device/pair`

External API: Get pairing code for a phone number

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `phone` | query | string | Ya | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/device/logout`

External API: Logout and delete WhatsApp session

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `phone` | query | string | Ya | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/groups`

External API: Get list of joined groups

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/group-info`

External API: Get group metadata and participants with LID to PN conversion

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `group_jid` | query | string | Ya | `—` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/send-message`

External API: Send a text message using query params and x-api-key header

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `to` | query | string | Ya | `—` |
| `text` | query | string | Ya | `—` |
| `mentions` | query | string / null | Tidak | `—` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/send-image`

External API: Send an image via URL using query params

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `to` | query | string | Ya | `—` |
| `image_url` | query | string | Ya | `—` |
| `caption` | query | string / null | Tidak | `""` |
| `hd` | query | boolean | Tidak | `false` |
| `mentions` | query | string / null | Tidak | `—` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/send-audio`

External API: Send audio using query params

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `to` | query | string | Ya | `—` |
| `audio_url` | query | string | Ya | `—` |
| `ptt` | query | boolean | Tidak | `false` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/send-video`

External API: Send video using query params

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `to` | query | string | Ya | `—` |
| `video_url` | query | string | Ya | `—` |
| `caption` | query | string / null | Tidak | `""` |
| `hd` | query | boolean | Tidak | `false` |
| `viewonce` | query | boolean | Tidak | `false` |
| `mentions` | query | string / null | Tidak | `—` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/send-document`

External API: Send document using query params

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `to` | query | string | Ya | `—` |
| `document_url` | query | string | Ya | `—` |
| `caption` | query | string / null | Tidak | `""` |
| `title` | query | string / null | Tidak | `""` |
| `filename` | query | string / null | Tidak | `""` |
| `mimetype` | query | string / null | Tidak | `""` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/send-sticker`

External API: Send sticker using query params

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `to` | query | string | Ya | `—` |
| `sticker_url` | query | string | Ya | `—` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## POST `/api/newsletter/send`

Dedicated API: Send message/media to a Newsletter channel. 'to' can be JID or URL.

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `to` | query | string | Ya | `—` |
| `type` | query | string | Tidak | `"text"` |
| `text` | query | string / null | Tidak | `""` |
| `media_url` | query | string / null | Tidak | `—` |
| `caption` | query | string / null | Tidak | `""` |
| `hd` | query | boolean | Tidak | `false` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/newsletter/list`

External API: List Subscribed Newsletters with Full Details

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/newsletter/info-by-invite`

External API: Get Newsletter Info by Invite Key or URL.
- key: The invite key (e.g. 0029VajW...) or the full URL.

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `key` | query | string | Ya | `—` |
| `phone` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/newsletter/info`

External API: Get Newsletter Info

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `jid` | query | string | Ya | `—` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## POST `/api/newsletter/follow`

External API: Follow a Newsletter

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `jid` | query | string | Ya | `—` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## POST `/api/newsletter/unfollow`

External API: Unfollow a Newsletter

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `jid` | query | string | Ya | `—` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/newsletter/messages`

External API: Get Newsletter Messages

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `jid` | query | string | Ya | `—` |
| `count` | query | integer | Tidak | `10` |
| `before` | query | integer / null | Tidak | `—` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## POST `/api/newsletter/create`

External API: Create a Newsletter (Channel)

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `name` | query | string | Ya | `—` |
| `description` | query | string | Tidak | `""` |
| `phone` | query | string / null | Tidak | `—` |
| `picture` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/send-contact`

External API: Send contact card using query params

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `to` | query | string | Ya | `—` |
| `contact_name` | query | string | Ya | `—` |
| `contact_number` | query | string | Ya | `—` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## POST `/api/send-location`

Api Send Location

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Body: **application/json**.

| Field | Tipe | Wajib | Default |
| --- | --- | --- | --- |
| `to` | string | Ya | `—` |
| `phone` | string / null | Tidak | `—` |
| `latitude` | number | Ya | `—` |
| `longitude` | number | Ya | `—` |
| `name` | string / null | Tidak | `—` |
| `address` | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## POST `/api/send-poll`

Api Send Poll

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Body: **application/json**.

| Field | Tipe | Wajib | Default |
| --- | --- | --- | --- |
| `to` | string | Ya | `—` |
| `phone` | string / null | Tidak | `—` |
| `question` | string | Ya | `—` |
| `options` | array[string] | Ya | `—` |
| `allow_multiple` | boolean | Tidak | `false` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## POST `/api/send-reaction`

Api Send Reaction

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Body: **application/json**.

| Field | Tipe | Wajib | Default |
| --- | --- | --- | --- |
| `to` | string | Ya | `—` |
| `phone` | string / null | Tidak | `—` |
| `message_id` | string | Ya | `—` |
| `reaction` | string | Ya | `—` |
| `sender` | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/send-interactive`

External API: Send interactive message via GET.
Payload must be a JSON string.

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `to` | query | string | Ya | `—` |
| `payload` | query | string | Ya | `—` |
| `media_url` | query | string / null | Tidak | `—` |
| `media_type` | query | string / null | Tidak | `"image"` |
| `hd` | query | boolean | Tidak | `false` |
| `mentions` | query | string / null | Tidak | `—` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## POST `/api/send-interactive`

External API: Send interactive message via POST.

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Body: **application/json**.

| Field | Tipe | Wajib | Default |
| --- | --- | --- | --- |
| `to` | string | Ya | `—` |
| `payload` | object | Ya | `—` |
| `phone` | string / null | Tidak | `—` |
| `media_url` | string / null | Tidak | `—` |
| `media_type` | string / null | Tidak | `"image"` |
| `mentions` | string / null | Tidak | `—` |
| `hd` | boolean | Tidak | `false` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## POST `/api/send-buttonv2`

External API: Send ButtonV2 (legacy buttons) via POST.

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Body: **application/json**.

| Field | Tipe | Wajib | Default |
| --- | --- | --- | --- |
| `to` | string | Ya | `—` |
| `phone` | string / null | Tidak | `—` |
| `title` | string / null | Tidak | `—` |
| `subtitle` | string / null | Tidak | `—` |
| `body` | string | Ya | `—` |
| `footer` | string / null | Tidak | `—` |
| `thumbnail_url` | string / null | Tidak | `—` |
| `buttons` | array[ButtonV2ItemPayload] | Ya | `—` |
| `mentions` | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/send-buttonv2`

External API: Send ButtonV2 (legacy buttons) via GET.

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `to` | query | string | Ya | `—` |
| `body` | query | string | Ya | `—` |
| `buttons` | query | string | Ya | `—` |
| `title` | query | string / null | Tidak | `—` |
| `subtitle` | query | string / null | Tidak | `—` |
| `footer` | query | string / null | Tidak | `—` |
| `thumbnail_url` | query | string / null | Tidak | `—` |
| `mentions` | query | string / null | Tidak | `—` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## POST `/api/airich/preview`

Build the message without sending. This is a protobuf preview, not a WhatsApp render.

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Body: **application/json**.

| Field | Tipe | Wajib | Default |
| --- | --- | --- | --- |
| `to` | string | Ya | `—` |
| `phone` | string / null | Tidak | `—` |
| `title` | string / null | Tidak | `—` |
| `footer` | string / null | Tidak | `—` |
| `mentions` | string / null | Tidak | `—` |
| `blocks` | array[AIRichBlock] | Tidak | `—` |
| `submessages` | array[object] / null | Tidak | `—` |
| `unified` | object / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## POST `/api/send-airich`

Send AI Rich blocks, including experimental HTML primitives.

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Body: **application/json**.

| Field | Tipe | Wajib | Default |
| --- | --- | --- | --- |
| `to` | string | Ya | `—` |
| `phone` | string / null | Tidak | `—` |
| `title` | string / null | Tidak | `—` |
| `footer` | string / null | Tidak | `—` |
| `mentions` | string / null | Tidak | `—` |
| `blocks` | array[AIRichBlock] | Tidak | `—` |
| `submessages` | array[object] / null | Tidak | `—` |
| `unified` | object / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/send-airich`

GET uses the same validated payload and builder as POST.

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `to` | query | string | Ya | `—` |
| `payload` | query | string | Ya | `—` |
| `mentions` | query | string / null | Tidak | `—` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/send-status`

External API: Send WhatsApp Status (Story)
type: 'text', 'image', or 'video'
Media is uploaded from the source file; hd is retained for API compatibility.

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `type` | query | string | Ya | `—` |
| `text` | query | string / null | Tidak | `""` |
| `url` | query | string / null | Tidak | `""` |
| `mentions` | query | string / null | Tidak | `—` |
| `hd` | query | boolean | Tidak | `false` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/send-group-status`

External API: Send WhatsApp Group Status (Story to specific Group)
to: Group JID
type: 'text', 'image', or 'video'

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `to` | query | string | Ya | `—` |
| `type` | query | string | Ya | `—` |
| `text` | query | string / null | Tidak | `""` |
| `url` | query | string / null | Tidak | `""` |
| `mentions` | query | string / null | Tidak | `—` |
| `hd` | query | boolean | Tidak | `false` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/convert-jid`

External API: Convert JID between LID and PN.
If PN JID provided, returns LID JID.
If LID JID provided, returns PN JID.

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `jid` | query | string | Ya | `—` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/check-number`

External API: Check if a number is registered on WhatsApp and get ALL available profile info from neonize

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `phone_to_check` | query | string | Ya | `—` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## GET `/api/resend`

External API: Resend a message from the logs

| Nama | Lokasi | Tipe | Wajib | Default |
| --- | --- | --- | --- | --- |
| `log_id` | query | integer | Ya | `—` |
| `phone` | query | string / null | Tidak | `—` |
| `key` | query | string / null | Tidak | `—` |
| `x-api-key` | header | string / null | Tidak | `—` |

Respons dan batas field mengikuti schema lengkap di `/openapi.json`.

## Schema payload

### LocationSendPayload

```json
{
  "properties": {
    "to": {
      "type": "string",
      "title": "To"
    },
    "phone": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Phone"
    },
    "latitude": {
      "type": "number",
      "maximum": 90.0,
      "minimum": -90.0,
      "title": "Latitude"
    },
    "longitude": {
      "type": "number",
      "maximum": 180.0,
      "minimum": -180.0,
      "title": "Longitude"
    },
    "name": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Name"
    },
    "address": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Address"
    }
  },
  "type": "object",
  "required": [
    "to",
    "latitude",
    "longitude"
  ],
  "title": "LocationSendPayload"
}
```

### PollSendPayload

```json
{
  "properties": {
    "to": {
      "type": "string",
      "title": "To"
    },
    "phone": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Phone"
    },
    "question": {
      "type": "string",
      "maxLength": 255,
      "minLength": 1,
      "title": "Question"
    },
    "options": {
      "items": {
        "type": "string"
      },
      "type": "array",
      "maxItems": 12,
      "minItems": 2,
      "title": "Options"
    },
    "allow_multiple": {
      "type": "boolean",
      "title": "Allow Multiple",
      "default": false
    }
  },
  "type": "object",
  "required": [
    "to",
    "question",
    "options"
  ],
  "title": "PollSendPayload"
}
```

### ReactionSendPayload

```json
{
  "properties": {
    "to": {
      "type": "string",
      "title": "To"
    },
    "phone": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Phone"
    },
    "message_id": {
      "type": "string",
      "minLength": 1,
      "title": "Message Id"
    },
    "reaction": {
      "type": "string",
      "maxLength": 8,
      "minLength": 1,
      "title": "Reaction"
    },
    "sender": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Sender"
    }
  },
  "type": "object",
  "required": [
    "to",
    "message_id",
    "reaction"
  ],
  "title": "ReactionSendPayload"
}
```

### InteractivePayload

```json
{
  "properties": {
    "to": {
      "type": "string",
      "title": "To"
    },
    "payload": {
      "additionalProperties": true,
      "type": "object",
      "title": "Payload"
    },
    "phone": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Phone"
    },
    "media_url": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Media Url"
    },
    "media_type": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Media Type",
      "default": "image"
    },
    "mentions": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Mentions"
    },
    "hd": {
      "type": "boolean",
      "title": "Hd",
      "default": false
    }
  },
  "type": "object",
  "required": [
    "to",
    "payload"
  ],
  "title": "InteractivePayload"
}
```

### ButtonV2Payload

```json
{
  "properties": {
    "to": {
      "type": "string",
      "title": "To"
    },
    "phone": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Phone"
    },
    "title": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Title"
    },
    "subtitle": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Subtitle"
    },
    "body": {
      "type": "string",
      "minLength": 1,
      "title": "Body"
    },
    "footer": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Footer"
    },
    "thumbnail_url": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Thumbnail Url"
    },
    "buttons": {
      "items": {
        "$ref": "#/components/schemas/ButtonV2ItemPayload"
      },
      "type": "array",
      "maxItems": 3,
      "minItems": 1,
      "title": "Buttons"
    },
    "mentions": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Mentions"
    }
  },
  "type": "object",
  "required": [
    "to",
    "body",
    "buttons"
  ],
  "title": "ButtonV2Payload"
}
```

### ButtonV2ItemPayload

```json
{
  "properties": {
    "display_text": {
      "type": "string",
      "maxLength": 25,
      "minLength": 1,
      "title": "Display Text"
    },
    "button_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Button Id"
    }
  },
  "type": "object",
  "required": [
    "display_text"
  ],
  "title": "ButtonV2ItemPayload"
}
```

### AIRichPayload

```json
{
  "properties": {
    "to": {
      "type": "string",
      "minLength": 1,
      "title": "To"
    },
    "phone": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Phone"
    },
    "title": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Title"
    },
    "footer": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Footer"
    },
    "mentions": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Mentions"
    },
    "blocks": {
      "items": {
        "$ref": "#/components/schemas/AIRichBlock"
      },
      "type": "array",
      "title": "Blocks"
    },
    "submessages": {
      "anyOf": [
        {
          "items": {
            "additionalProperties": true,
            "type": "object"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "title": "Submessages"
    },
    "unified": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "type": "null"
        }
      ],
      "title": "Unified"
    }
  },
  "type": "object",
  "required": [
    "to"
  ],
  "title": "AIRichPayload"
}
```

### AIRichBlock

```json
{
  "properties": {
    "type": {
      "type": "string",
      "enum": [
        "text",
        "code",
        "table",
        "image",
        "video",
        "source",
        "product",
        "reels",
        "post",
        "tip",
        "suggest",
        "html"
      ],
      "title": "Type"
    },
    "text": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Text"
    },
    "latex": {
      "type": "boolean",
      "title": "Latex",
      "default": true
    },
    "hyperlink": {
      "type": "boolean",
      "title": "Hyperlink",
      "default": true
    },
    "citation": {
      "type": "boolean",
      "title": "Citation",
      "default": true
    },
    "language": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Language"
    },
    "html": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 500000
        },
        {
          "type": "null"
        }
      ],
      "title": "Html"
    },
    "trusted_sources": {
      "items": {
        "type": "string"
      },
      "type": "array",
      "title": "Trusted Sources"
    },
    "code": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Code"
    },
    "table": {
      "anyOf": [
        {
          "items": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "title": "Table"
    },
    "url": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "title": "Url"
    },
    "duration": {
      "type": "integer",
      "minimum": 0.0,
      "title": "Duration",
      "default": 0
    },
    "source": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "items": {
            "additionalProperties": true,
            "type": "object"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "title": "Source"
    },
    "product": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "items": {
            "additionalProperties": true,
            "type": "object"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "title": "Product"
    },
    "reel": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "items": {
            "additionalProperties": true,
            "type": "object"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "title": "Reel"
    },
    "post": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "items": {
            "additionalProperties": true,
            "type": "object"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "title": "Post"
    },
    "suggestions": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "title": "Suggestions"
    }
  },
  "type": "object",
  "required": [
    "type"
  ],
  "title": "AIRichBlock"
}
```
