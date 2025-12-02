"""Standalone CLI for layout analysis of URLs or existing components."""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Error: playwright is not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)

from .layout_analyzer import analyze_layout

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


def analyze_url(url: str, output_path: Optional[str] = None, 
                component_id: Optional[str] = None,
                component_name: Optional[str] = None,
                browser_executable: Optional[str] = None) -> dict:
    """
    Analyze layout of a URL.
    
    Args:
        url: URL to analyze
        output_path: Optional path to save layout JSON
        component_id: Optional component identifier
        component_name: Optional component name
        browser_executable: Optional path to Chromium/Chrome executable
        
    Returns:
        Layout analysis dictionary
    """
    logger.info(f"Analyzing layout for URL: {url}")
    
    try:
        with sync_playwright() as p:
            launch_kwargs = {
                "headless": True,
            }
            if browser_executable:
                launch_kwargs["executable_path"] = browser_executable
                logger.info(f"Using custom Chromium binary at {browser_executable}")

            try:
                browser = p.chromium.launch(**launch_kwargs)
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Failed to launch browser: {error_msg}")
                if "Executable doesn't exist" in error_msg or "browserType.launch" in error_msg:
                    logger.error("Playwright browsers may not be installed.")
                    logger.info("Try running: playwright install chromium")
                raise
            
            try:
                page = browser.new_page()
                
                try:
                    page.goto(url, wait_until="networkidle", timeout=60000)
                    layout = analyze_layout(page, component_id, component_name)
                    
                    if output_path:
                        output_file = Path(output_path)
                        output_file.parent.mkdir(parents=True, exist_ok=True)
                        with open(output_file, 'w', encoding='utf-8') as f:
                            json.dump(layout, f, indent=2, ensure_ascii=False)
                        logger.info(f"Layout analysis saved to {output_path}")
                    
                    return layout
                    
                except Exception as e:
                    logger.error(f"Error analyzing URL {url}: {str(e)}")
                    raise
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"Error in layout analysis: {str(e)}")
        raise


def analyze_existing_component(component_path: str, output_path: Optional[str] = None,
                               browser_executable: Optional[str] = None) -> dict:
    """
    Analyze layout of an existing scraped component by loading its metadata.
    
    Args:
        component_path: Path to component directory (should contain metadata.json)
        output_path: Optional path to save layout JSON (defaults to component_path/layout.json)
        browser_executable: Optional path to Chromium/Chrome executable
        
    Returns:
        Layout analysis dictionary
    """
    component_dir = Path(component_path)
    if not component_dir.exists():
        raise ValueError(f"Component directory does not exist: {component_path}")
    
    metadata_path = component_dir / "metadata.json"
    if not metadata_path.exists():
        raise ValueError(f"Metadata file not found: {metadata_path}")
    
    with open(metadata_path, 'r', encoding='utf-8') as f:
        metadata = json.load(f)
    
    url = metadata.get('url')
    if not url:
        raise ValueError(f"No URL found in metadata for component: {component_path}")
    
    component_name = metadata.get('name', component_dir.name)
    component_id = metadata.get('slug') or component_dir.name
    
    if not output_path:
        output_path = str(component_dir / "layout.json")
    
    return analyze_url(url, output_path, component_id, component_name, browser_executable)


def main():
    """Main entry point for layout analysis CLI."""
    parser = argparse.ArgumentParser(
        description='Analyze layout structure of web pages or existing components'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # URL analysis command
    url_parser = subparsers.add_parser('url', help='Analyze layout of a URL')
    url_parser.add_argument('url', help='URL to analyze')
    url_parser.add_argument('-o', '--output', help='Output path for layout JSON')
    url_parser.add_argument('--id', help='Component identifier')
    url_parser.add_argument('--name', help='Component name')
    url_parser.add_argument('--browser-path', help='Path to Chromium/Chrome executable')
    
    # Component analysis command
    component_parser = subparsers.add_parser('component', help='Analyze existing component')
    component_parser.add_argument('path', help='Path to component directory')
    component_parser.add_argument('-o', '--output', help='Output path for layout JSON (defaults to component_path/layout.json)')
    component_parser.add_argument('--browser-path', help='Path to Chromium/Chrome executable')
    
    # Batch analysis command
    batch_parser = subparsers.add_parser('batch', help='Analyze multiple components')
    batch_parser.add_argument('components_dir', help='Path to components directory (e.g., library/aceternity/components)')
    batch_parser.add_argument('--browser-path', help='Path to Chromium/Chrome executable')
    batch_parser.add_argument('--limit', type=int, help='Limit number of components to analyze')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    try:
        if args.command == 'url':
            layout = analyze_url(
                args.url,
                args.output,
                args.id,
                args.name,
                args.browser_path,
            )
            print(json.dumps(layout, indent=2))
            
        elif args.command == 'component':
            layout = analyze_existing_component(
                args.path,
                args.output,
                args.browser_path,
            )
            print(json.dumps(layout, indent=2))
            
        elif args.command == 'batch':
            components_dir = Path(args.components_dir)
            if not components_dir.exists():
                raise ValueError(f"Components directory does not exist: {args.components_dir}")
            
            component_dirs = [d for d in components_dir.iterdir() if d.is_dir()]
            if args.limit:
                component_dirs = component_dirs[:args.limit]
            
            logger.info(f"Analyzing {len(component_dirs)} components...")
            
            successful = 0
            failed = 0
            
            for component_dir in component_dirs:
                try:
                    logger.info(f"Analyzing component: {component_dir.name}")
                    analyze_existing_component(
                        str(component_dir),
                        None,  # Use default output path
                        args.browser_path,
                    )
                    successful += 1
                except Exception as e:
                    logger.error(f"Failed to analyze {component_dir.name}: {str(e)}")
                    failed += 1
            
            logger.info(f"Batch analysis complete! Successful: {successful}, Failed: {failed}")
            
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        raise


if __name__ == '__main__':
    main()

