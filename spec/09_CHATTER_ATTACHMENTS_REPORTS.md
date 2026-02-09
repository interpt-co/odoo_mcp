# 09 — Chatter, Attachments & Reports

| Field        | Value                              |
|-------------|-------------------------------------|
| Document ID | SPEC-09                             |
| Title       | Chatter, Attachments & Reports       |
| Status      | Draft                               |
| Depends On  | SPEC-04, SPEC-07                    |
| Referenced By | —                                  |

---

## 1. Overview

This document specifies three related capabilities that handle Odoo's communication and document subsystems:

1. **Chatter** — Odoo's built-in messaging system (`mail.message`, `mail.activity`) available on any model inheriting `mail.thread`.
2. **Attachments** — File upload/download via `ir.attachment`.
3. **Reports** — PDF document generation from Odoo's QWeb report engine.

---

## 2. Chatter Toolset (`chatter`)

**Required module**: `mail`

### 2.1 odoo_chatter_get_messages

**REQ-09-01**: Retrieve messages from a record's chatter.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "model": {
      "type": "string",
      "description": "Odoo model name (must have chatter, e.g., 'sale.order')"
    },
    "record_id": {
      "type": "integer",
      "description": "Record ID"
    },
    "limit": {
      "type": "integer",
      "default": 20,
      "maximum": 100
    },
    "message_types": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": ["email", "comment", "notification", "auto_comment", "user_notification"]
      },
      "description": "Filter by message type. Default: ['email', 'comment'] (excludes system notifications).",
      "default": ["email", "comment"]
    },
    "strip_html": {
      "type": "boolean",
      "description": "Strip HTML from message bodies. Default: true.",
      "default": true
    }
  },
  "required": ["model", "record_id"]
}
```

**REQ-09-02**: Implementation:
```python
domain = [
    ('model', '=', model),
    ('res_id', '=', record_id),
    ('message_type', 'in', message_types),
]
messages = await connection.search_read(
    'mail.message', domain,
    fields=['id', 'body', 'author_id', 'date', 'message_type', 'subtype_id', 'email_from', 'subject'],
    order='date desc',
    limit=limit,
)
```

**REQ-09-03**: Response format:
```json
{
  "model": "helpdesk.ticket",
  "record_id": 42,
  "messages": [
    {
      "id": 101,
      "date": "2025-02-09T14:30:00Z",
      "author": {"id": 2, "name": "John Smith"},
      "type": "comment",
      "subject": null,
      "body": "Plain text message content here",
      "email_from": "john@example.com"
    }
  ],
  "count": 1,
  "has_more": false
}
```

### 2.2 odoo_chatter_post_message

**REQ-09-04**: Post a message to a record's chatter.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "model": {
      "type": "string",
      "description": "Odoo model name"
    },
    "record_id": {
      "type": "integer"
    },
    "body": {
      "type": "string",
      "description": "Message body (plain text, will be wrapped in <p> tags)"
    },
    "message_type": {
      "type": "string",
      "enum": ["comment", "notification"],
      "default": "comment",
      "description": "comment = visible in chatter, notification = internal note"
    },
    "subtype": {
      "type": "string",
      "description": "Message subtype XML ID. Default: 'mail.mt_comment' for comments, 'mail.mt_note' for internal notes.",
      "default": null
    },
    "partner_ids": {
      "type": "array",
      "items": { "type": "integer" },
      "description": "Partner IDs to notify"
    }
  },
  "required": ["model", "record_id", "body"]
}
```

**REQ-09-05**: Implementation uses `message_post`:
```python
result = await connection.execute_kw(model, 'message_post', [record_id], {
    'body': f'<p>{body}</p>',
    'message_type': message_type,
    'subtype_xmlid': subtype or ('mail.mt_comment' if message_type == 'comment' else 'mail.mt_note'),
    'partner_ids': partner_ids or [],
})
```

**REQ-09-06**: The tool MUST check operation mode: not allowed in `readonly` mode.

### 2.3 odoo_chatter_get_activities

**REQ-09-07**: Retrieve scheduled activities for a record.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "model": {
      "type": "string"
    },
    "record_id": {
      "type": "integer"
    }
  },
  "required": ["model", "record_id"]
}
```

**REQ-09-08**: Queries `mail.activity`:
```python
domain = [
    ('res_model', '=', model),
    ('res_id', '=', record_id),
]
activities = await connection.search_read(
    'mail.activity', domain,
    fields=['id', 'activity_type_id', 'summary', 'note', 'date_deadline', 'user_id', 'state'],
    order='date_deadline asc',
)
```

### 2.4 odoo_chatter_schedule_activity

**REQ-09-09**: Schedule a new activity on a record.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "model": { "type": "string" },
    "record_id": { "type": "integer" },
    "activity_type": {
      "type": "string",
      "description": "Activity type: 'email', 'call', 'meeting', 'todo', 'upload_document'. Maps to mail.activity.type.",
      "default": "todo"
    },
    "summary": { "type": "string", "description": "Activity title" },
    "note": { "type": "string", "description": "Activity description" },
    "date_deadline": { "type": "string", "description": "Due date (YYYY-MM-DD). Default: today." },
    "user_id": { "type": "integer", "description": "Assigned user ID. Default: current user." }
  },
  "required": ["model", "record_id", "summary"]
}
```

**REQ-09-10**: The tool MUST resolve `activity_type` string to the corresponding `mail.activity.type` ID:
```python
activity_type_map = {
    'email': 'mail.mail_activity_data_email',
    'call': 'mail.mail_activity_data_call',
    'meeting': 'mail.mail_activity_data_meeting',
    'todo': 'mail.mail_activity_data_todo',
    'upload_document': 'mail.mail_activity_data_upload_document',
}
```

---

## 3. Attachments Toolset (`attachments`)

### 3.1 odoo_attachments_list

**REQ-09-11**: List attachments for a record.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "model": { "type": "string" },
    "record_id": { "type": "integer" }
  },
  "required": ["model", "record_id"]
}
```

**REQ-09-12**: Queries `ir.attachment`:
```python
domain = [
    ('res_model', '=', model),
    ('res_id', '=', record_id),
]
attachments = await connection.search_read(
    'ir.attachment', domain,
    fields=['id', 'name', 'mimetype', 'file_size', 'create_date', 'create_uid'],
    order='create_date desc',
)
```

**REQ-09-13**: Response format:
```json
{
  "model": "helpdesk.ticket",
  "record_id": 42,
  "attachments": [
    {
      "id": 101,
      "name": "screenshot.png",
      "mimetype": "image/png",
      "file_size": 245760,
      "file_size_human": "240 KB",
      "created_at": "2025-02-09T14:30:00Z",
      "created_by": {"id": 2, "name": "John Smith"}
    }
  ],
  "count": 1
}
```

### 3.2 odoo_attachments_get_content

**REQ-09-14**: Download attachment content.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "attachment_id": { "type": "integer" },
    "as_text": {
      "type": "boolean",
      "description": "If true, attempt to decode binary content as text. Only works for text MIME types.",
      "default": false
    }
  },
  "required": ["attachment_id"]
}
```

**REQ-09-15**: The tool MUST enforce safety limits:
- Maximum attachment size for download: 12 MB (configurable).
- Only allowed MIME types for text decoding:
  ```python
  TEXT_MIME_TYPES = {
      'text/plain', 'text/csv', 'text/html', 'text/xml',
      'application/json', 'application/xml', 'application/xhtml+xml',
  }
  ```
- Binary content (images, PDFs) is returned as base64.
- Attachments exceeding the size limit return metadata only with a warning.

**REQ-09-16**: Response:
```json
{
  "id": 101,
  "name": "data.csv",
  "mimetype": "text/csv",
  "file_size": 1024,
  "content": "id,name,value\n1,test,42\n...",
  "encoding": "text"
}
```

For binary:
```json
{
  "id": 102,
  "name": "screenshot.png",
  "mimetype": "image/png",
  "file_size": 245760,
  "content_base64": "iVBORw0KGgo...",
  "encoding": "base64"
}
```

### 3.3 odoo_attachments_upload

**REQ-09-17**: Upload a file as an attachment to a record.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "model": { "type": "string", "description": "Target model" },
    "record_id": { "type": "integer", "description": "Target record ID" },
    "name": { "type": "string", "description": "File name (e.g., 'report.pdf')" },
    "content_base64": { "type": "string", "description": "File content as base64 string" },
    "mimetype": { "type": "string", "description": "MIME type. Auto-detected from file name if omitted." }
  },
  "required": ["model", "record_id", "name", "content_base64"]
}
```

**REQ-09-18**: Creates an `ir.attachment` record:
```python
values = {
    'name': name,
    'datas': content_base64,  # Odoo stores binary data in 'datas' field
    'res_model': model,
    'res_id': record_id,
    'mimetype': mimetype or guess_mimetype(name),
}
attachment_id = await connection.execute_kw('ir.attachment', 'create', [values])
```

**REQ-09-19**: The tool MUST check operation mode: not allowed in `readonly` mode.

### 3.4 odoo_attachments_delete

**REQ-09-20**: Delete an attachment.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "attachment_id": { "type": "integer" }
  },
  "required": ["attachment_id"]
}
```

**REQ-09-21**: Only allowed in `full` operation mode. Tool annotation: `destructiveHint: true`.

---

## 4. Reports Toolset (`reports`)

### 4.1 odoo_reports_generate

**REQ-09-22**: Generate a PDF report for a record.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "report_name": {
      "type": "string",
      "description": "Report technical name. Examples: 'sale.report_saleorder', 'account.report_invoice', 'stock.report_picking'"
    },
    "record_ids": {
      "type": "array",
      "items": { "type": "integer" },
      "description": "Record IDs to include in the report",
      "minItems": 1,
      "maxItems": 20
    },
    "context": {
      "type": "object",
      "description": "Additional context for report rendering"
    }
  },
  "required": ["report_name", "record_ids"]
}
```

**REQ-09-23**: Report generation differs by protocol:

**XML-RPC (Odoo 14-16)**:
```python
# Use /xmlrpc/2/report endpoint
report_data = xmlrpc_report.render_report(
    database, uid, password, report_name, record_ids
)
# Returns {'result': base64_pdf, 'format': 'pdf'}
```

**JSON-2 (Odoo 17+)**:
```python
# Use /report/download endpoint or execute ir.actions.report
result = await connection.execute_kw(
    'ir.actions.report', '_render_qweb_pdf',
    [report_name, record_ids],
)
```

**REQ-09-24**: Response:
```json
{
  "report_name": "sale.report_saleorder",
  "record_ids": [42],
  "format": "pdf",
  "content_base64": "JVBERi0xLjQ...",
  "file_name": "SO042.pdf",
  "size": 45678,
  "size_human": "44.6 KB"
}
```

### 4.2 odoo_reports_list

**REQ-09-25**: List available reports for a model.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "model": {
      "type": "string",
      "description": "Odoo model name to list reports for"
    }
  },
  "required": ["model"]
}
```

**REQ-09-26**: Queries `ir.actions.report`:
```python
domain = [('model', '=', model)]
reports = await connection.search_read(
    'ir.actions.report', domain,
    fields=['name', 'report_name', 'report_type', 'print_report_name'],
)
```

Response:
```json
{
  "model": "sale.order",
  "reports": [
    {
      "name": "Quotation / Order",
      "report_name": "sale.report_saleorder",
      "report_type": "qweb-pdf"
    },
    {
      "name": "PRO-FORMA Invoice",
      "report_name": "sale.report_saleorder_pro_forma",
      "report_type": "qweb-pdf"
    }
  ]
}
```
