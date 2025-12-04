# Database Integration for Component Scraper

The component scraper can now automatically convert and save scraped templates directly to the FlowRunner database.

## Setup

1. **Install database dependency:**
   ```bash
   pip install psycopg2-binary
   ```

2. **Set environment variables:**
   Create a `.env` file or export:
   ```bash
   export DATABASE_URL="postgresql://user:password@host:port/database?schema=public"
   export SAVE_TEMPLATES_TO_DB=true
   ```

## Usage

### Automatic Saving

When `SAVE_TEMPLATES_TO_DB=true`, templates are automatically converted and saved to the database after layout analysis:

```bash
export SAVE_TEMPLATES_TO_DB=true
export DATABASE_URL="postgresql://..."
python -m scraper.layout_cli analyze_url https://example.com
```

### Manual Conversion

You can also use the converter module directly:

```python
from scraper.db_converter import convert_and_save
import json

# Load scraped template
with open('scraped_template.json') as f:
    scraped = json.load(f)

# Convert and save
converted = convert_and_save(
    scraped,
    template_name="My Template",
    save_to_db=True
)
```

## What Gets Saved

- **Template ID**: From scraped template `id` field
- **Template Name**: From `component_name` or auto-generated
- **Screen Type**: Mapped from scraped `screenType` ("page" → "landing")
- **Sections**: Converted with pixel coordinates (from normalized 0-1)
- **Slots**: Converted with proper types and roles
- **Repeated Groups**: Preserved if present

## Conversion Details

- Normalized bounding boxes (0-1) are converted to pixel coordinates
- Slot types: "container" → "content", "image" → "image"
- Roles are mapped to FlowRunner role types
- Screen type "page" is mapped to "landing"

## Troubleshooting

### Database Connection Error
- Verify `DATABASE_URL` is set correctly
- Ensure database is accessible
- Check PostgreSQL is running

### Template Not Saving
- Check `SAVE_TEMPLATES_TO_DB=true` is set
- Verify `psycopg2-binary` is installed
- Check logs for error messages

### Duplicate Templates
- Templates with the same ID will be updated (upserted)
- Change the `component_id` or `component_name` to create new templates

