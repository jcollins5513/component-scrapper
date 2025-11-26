# Component Scraper for Aceternity UI

A Python-based web scraper that extracts non-pro components from [Aceternity UI](https://ui.aceternity.com), capturing both visual examples (screenshots) and code examples, organized in a structured library.

## Features

- Scrapes multiple sources (Aceternity UI, Aura Build templates, Magic UI components)
- Extracts rich metadata (name, description, props, component type, layout role, recommended slots, tags)
- Captures preview and/or code screenshots (configurable, with image fallbacks)
- Extracts code examples with language + dependency detection
- Organizes components per source in a structured library format
- Generates source-specific index files for downstream tooling

## Requirements

- Python 3.8 or higher
- Playwright browser binaries

## Installation

1. Clone or navigate to this repository:
```bash
cd component-scrapper
```

2. Create a virtual environment (recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Install Playwright browsers:
```bash
playwright install chromium
```

## Usage

### Basic Usage

Run the scraper with default settings:
```bash
python -m scraper.main
```

### Command Line Options

```bash
python -m scraper.main [OPTIONS]
```

Options:
- `--output`, `-o`: Output directory (default: `library`)
- `--max`, `-m`: Maximum number of components to scrape (default: all)
- `--delay`, `-d`: Delay between requests in seconds (default: 2.0)
- `--url`: Base URL for Aceternity UI (default: `https://ui.aceternity.com`)
- `--browser-path`: Path to a Chromium/Chrome executable (useful if bundled Chromium fails)
- `--source`: Catalogue to scrape (`aceternity`, `aura`, `magic`; default `aceternity`)
- `--screenshots`: Which screenshots to capture (`preview`, `code`, or `both`; default `both`)

### Examples

Scrape first 10 components:
```bash
python -m scraper.main --max 10
```

Custom output directory with faster scraping:
```bash
python -m scraper.main --output my-components --delay 1.0
```

## Output Structure

The scraper creates the following directory structure:

```
library/
├── aceternity/
│   ├── components/
│   │   └── ...
│   └── index.json
├── aura/
│   ├── components/
│   │   └── ...
│   └── index.json
└── magic/
    ├── components/
    │   └── ...
    └── index.json
```

### Component Files

- **screenshot.png**: Visual example of the component (preview or downloaded thumbnail)
- **code.png**: Screenshot of the code tab (when available)
- **code.{ext}**: Code example (extension based on detected language)
- **metadata.json**: Component metadata including:
  - Name and description
  - Props schema (if available)
  - Component type, layout role, recommended slots, interaction profile
  - Category, tags, domain tags, and usage notes
  - Installation instructions, import statements, dependencies
  - Source URL and source-specific attributes (e.g., Aura author info)

### Index File

The `index.json` file contains a master list of all scraped components with summary information.

## Logging

The scraper logs its progress to both the console and a `scraper.log` file. Check the log file for detailed information about the scraping process.

## Error Handling

The scraper includes comprehensive error handling:
- Network timeouts and retries
- Graceful handling of missing components
- Skips components that fail to load
- Continues processing even if individual components fail

## Rate Limiting

By default, the scraper waits 2 seconds between requests to be respectful to the server. You can adjust this with the `--delay` option, but please be considerate.

## Notes

- Sources: Aceternity UI (free components), Aura Build featured templates, Magic UI documentation examples
- Aura templates are fetched via the public Supabase API and may be limited to featured/high-view items
- Screenshots can target previews and/or code tabs (configurable via `--screenshots`); preview thumbnails are downloaded when screenshots fail
- Code examples are pulled from the rendered code tab when available, with a fallback to embedded flight data
- Language detection is automatic (TSX, JSX, TS, JS, HTML)

## Troubleshooting

### Playwright Browser Issues

If you encounter browser-related errors, try reinstalling Playwright browsers:
```bash
playwright install --force chromium
```

### No Components Found

If no components are found:
- Check your internet connection
- Verify the Aceternity UI website is accessible
- Check the scraper.log file for detailed error messages

### Missing Screenshots or Code

Some components may not have screenshots or code examples if:
- The page structure is different than expected
- The component page failed to load
- The component is dynamically loaded and needs more time

Check the logs for specific error messages.

## License

This project is for educational and personal use. Please respect Aceternity UI's terms of service and use responsibly.

