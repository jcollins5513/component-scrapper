"""Standalone CLI for layout analysis of URLs or existing components."""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional, List

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


def _screen_type_to_folder_name(screen_type: str) -> str:
    """
    Map screen type to folder name.
    
    Args:
        screen_type: Screen type from layout analysis
        
    Returns:
        Folder name for the screen type
    """
    mapping = {
        'landing': 'Landingpage',
        'dashboard': 'Dashboard',
        'auth': 'Auth',
        'blog': 'Blog',
        'portfolio': 'Portfolio',
        'services': 'Services',
        'pricing': 'Pricing',
        'page': 'Page',
    }
    return mapping.get(screen_type, 'Page')


def _read_urls_from_file(url_file: str) -> List[str]:
    """
    Read URLs from a markdown file.
    
    Args:
        url_file: Path to the URL file (e.g., url.md)
        
    Returns:
        List of URLs extracted from the file
    """
    url_path = Path(url_file)
    if not url_path.exists():
        raise FileNotFoundError(f"URL file not found: {url_file}")
    
    urls = []
    with open(url_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith('#') or line.startswith('##'):
                continue
            # Extract URLs (lines starting with http:// or https://)
            if line.startswith('http://') or line.startswith('https://'):
                # Remove any trailing text after URL (like "404 Page")
                url = line.split()[0] if line.split() else line
                urls.append(url)
    
    logger.info(f"Read {len(urls)} URLs from {url_file}")
    return urls


def _find_system_chrome():
    """Try to find system Chrome/Chromium on macOS."""
    import os
    import subprocess
    
    # Common Chrome locations on macOS
    chrome_paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    ]
    
    for path in chrome_paths:
        if os.path.exists(path):
            return path
    
    # Try to find via mdfind (Spotlight search)
    try:
        result = subprocess.run(
            ["mdfind", "kMDItemCFBundleIdentifier == 'com.google.Chrome'"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            chrome_app = result.stdout.strip().split('\n')[0]
            chrome_binary = os.path.join(chrome_app, "Contents/MacOS/Google Chrome")
            if os.path.exists(chrome_binary):
                return chrome_binary
    except Exception:
        pass
    
    return None


def _launch_browser_with_retry(browser_executable: Optional[str] = None):
    """
    Try multiple browser launch strategies and return the browser and playwright instance.
    Tries Chromium first, then Firefox, then WebKit, then system Chrome.
    
    Returns:
        tuple: (playwright_instance, browser) or (None, None) if all strategies fail
    """
    import time
    import os
    
    # Try system Chrome if no executable specified
    system_chrome = None
    if not browser_executable:
        system_chrome = _find_system_chrome()
        if system_chrome:
            logger.info(f"Found system Chrome at: {system_chrome}")
    
    # Build browser strategies - try different browsers
    browser_strategies = []
    
    # Strategy 1: Try Chromium (Playwright's bundled)
    chromium_strategies = [
        {
            "browser_type": "chromium",
            "headless": True,
            "args": ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            "name": "Chromium headless with minimal args",
            "executable": browser_executable or system_chrome,
        },
        {
            "browser_type": "chromium",
            "headless": False,
            "args": ["--no-sandbox", "--disable-setuid-sandbox"],
            "name": "Chromium non-headless with minimal args",
            "executable": browser_executable or system_chrome,
        },
    ]
    browser_strategies.extend(chromium_strategies)
    
    # Strategy 2: Try Firefox (often more stable on macOS)
    firefox_strategies = [
        {
            "browser_type": "firefox",
            "headless": True,
            "args": [],
            "name": "Firefox headless",
            "executable": None,
        },
        {
            "browser_type": "firefox",
            "headless": False,
            "args": [],
            "name": "Firefox non-headless",
            "executable": None,
        },
    ]
    browser_strategies.extend(firefox_strategies)
    
    # Strategy 3: Try WebKit (Safari engine, native on macOS)
    webkit_strategies = [
        {
            "browser_type": "webkit",
            "headless": True,
            "args": [],
            "name": "WebKit headless",
            "executable": None,
        },
    ]
    browser_strategies.extend(webkit_strategies)
    
    last_error = None
    
    for strategy in browser_strategies:
        playwright_context = None
        browser = None
        try:
            playwright_context = sync_playwright()
            p = playwright_context.__enter__()
            
            browser_type = strategy["browser_type"]
            launch_kwargs = {
                "headless": strategy["headless"],
                "args": strategy["args"],
            }
            
            if strategy.get("executable"):
                launch_kwargs["executable_path"] = strategy["executable"]
                logger.info(f"Using browser executable at {strategy['executable']}")

            logger.info(f"Attempting browser launch: {strategy['name']}")
            try:
                # Launch the appropriate browser type
                if browser_type == "chromium":
                    browser = p.chromium.launch(**launch_kwargs)
                elif browser_type == "firefox":
                    browser = p.firefox.launch(**launch_kwargs)
                elif browser_type == "webkit":
                    browser = p.webkit.launch(**launch_kwargs)
                else:
                    continue
                
                # Small delay to ensure browser is fully initialized
                time.sleep(0.5)
                
                # Verify browser is actually running by creating a test context
                test_context = browser.new_context()
                test_context.close()
                
                logger.info(f"Browser launched successfully with {strategy['name']}")
                return (playwright_context, browser)
                
            except Exception as e:
                error_msg = str(e)
                last_error = e
                logger.warning(f"Browser launch failed with {strategy['name']}: {error_msg}")
                if browser:
                    try:
                        browser.close()
                    except Exception:
                        pass
                try:
                    playwright_context.__exit__(None, None, None)
                except Exception:
                    pass
                continue
                
        except Exception as e:
            last_error = e
            logger.warning(f"Playwright context error with {strategy['name']}: {str(e)}")
            if playwright_context:
                try:
                    playwright_context.__exit__(None, None, None)
                except Exception:
                    pass
            continue
    
    # All strategies failed
    if last_error:
        error_msg = str(last_error)
        logger.error(f"All browser launch strategies failed. Last error: {error_msg}")
        logger.error("Tried: Chromium (Playwright), Chromium (system), Firefox, and WebKit")
        if "Executable doesn't exist" in error_msg or "browserType.launch" in error_msg:
            logger.error("Playwright browsers may not be installed.")
            logger.info("Try running: playwright install chromium firefox webkit")
        elif "Target page, context or browser has been closed" in error_msg or "SEGV" in error_msg or "signal 11" in error_msg:
            logger.error("Browser crashed immediately after launch (segmentation fault).")
            logger.info("This is likely due to:")
            logger.info("  1. macOS security settings blocking the browser")
            logger.info("     - Go to System Preferences > Security & Privacy > General")
            logger.info("     - Allow the browser if it's blocked")
            logger.info("  2. Corrupted browser installation")
            logger.info("     - Try: playwright install --force chromium firefox webkit")
            logger.info("  3. Rosetta 2 compatibility issues (if on Apple Silicon)")
            logger.info("  4. Try installing Firefox: playwright install firefox")
            logger.info("  5. Use system Chrome with: --browser-path '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'")
        raise last_error
    
    raise RuntimeError("Failed to launch browser with any strategy")


def analyze_url(url: str, output_path: Optional[str] = None, 
                component_id: Optional[str] = None,
                component_name: Optional[str] = None,
                browser_executable: Optional[str] = None,
                browser_instance: Optional[object] = None,
                playwright_context: Optional[object] = None) -> dict:
    """
    Analyze layout of a URL.
    
    Args:
        url: URL to analyze
        output_path: Optional path to save layout JSON
        component_id: Optional component identifier
        component_name: Optional component name
        browser_executable: Optional path to Chromium/Chrome executable
        browser_instance: Optional browser instance to reuse (if provided, browser_executable is ignored)
        playwright_context: Optional playwright context (must be provided if browser_instance is provided)
        
    Returns:
        Layout analysis dictionary
    """
    logger.info(f"Analyzing layout for URL: {url}")
    
    should_close_browser = False
    should_close_playwright = False
    
    if browser_instance is None:
        # Launch browser with retry logic
        playwright_context, browser_instance = _launch_browser_with_retry(browser_executable)
        should_close_browser = True
        should_close_playwright = True
    
    try:
        # Create a new context for the page
        context = browser_instance.new_context()
        page = context.new_page()
        
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
            try:
                context.close()
            except Exception:
                pass
    finally:
        if should_close_browser and browser_instance:
            try:
                browser_instance.close()
            except Exception:
                pass
        if should_close_playwright and playwright_context:
            try:
                playwright_context.__exit__(None, None, None)
            except Exception:
                pass


def process_urls_batch(url_file: str = 'url.md', 
                       output_dir: str = '.',
                       browser_executable: Optional[str] = None) -> dict:
    """
    Process multiple URLs from a file, categorize by screen type, and save with sequential numbering.
    
    Args:
        url_file: Path to file containing URLs (default: url.md)
        output_dir: Output directory for categorized templates (default: current directory)
        browser_executable: Optional path to Chromium/Chrome executable
        
    Returns:
        Dictionary with processing statistics
    """
    from collections import defaultdict
    
    # Read URLs from file
    urls = _read_urls_from_file(url_file)
    
    if not urls:
        logger.warning(f"No URLs found in {url_file}")
        return {
            'total': 0,
            'successful': 0,
            'failed': 0,
            'by_category': {},
        }
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Track counts per category
    category_counts: dict[str, int] = defaultdict(int)
    stats = {
        'total': len(urls),
        'successful': 0,
        'failed': 0,
        'by_category': defaultdict(int),
    }
    
    playwright_context = None
    browser = None
    
    try:
        # Launch browser once for all URLs
        logger.info("Launching browser for batch processing...")
        playwright_context, browser = _launch_browser_with_retry(browser_executable)
        
        # Process each URL
        for i, url in enumerate(urls, 1):
            try:
                logger.info(f"Processing URL {i}/{len(urls)}: {url}")
                
                # Analyze URL (reuse browser instance)
                layout = analyze_url(
                    url,
                    output_path=None,  # We'll save it ourselves with proper naming
                    component_id=None,
                    component_name=None,
                    browser_executable=None,
                    browser_instance=browser,
                    playwright_context=playwright_context,
                )
                
                # Get screen type and map to folder name
                screen_type = layout.get('screenType', 'page')
                folder_name = _screen_type_to_folder_name(screen_type)
                
                # Increment count for this category
                category_counts[folder_name] += 1
                file_number = category_counts[folder_name]
                
                # Create category directory
                category_dir = output_path / folder_name
                category_dir.mkdir(parents=True, exist_ok=True)
                
                # Generate filename (e.g., landingpage1.json, dashboard2.json)
                filename = f"{folder_name.lower()}{file_number}.json"
                output_file = category_dir / filename
                
                # Save layout
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(layout, f, indent=2, ensure_ascii=False)
                
                logger.info(f"Saved to {output_file} (category: {folder_name}, number: {file_number})")
                stats['successful'] += 1
                stats['by_category'][folder_name] += 1
                
            except Exception as e:
                logger.error(f"Failed to process URL {url}: {str(e)}")
                stats['failed'] += 1
                continue
        
        logger.info(f"Batch processing complete! Successful: {stats['successful']}, Failed: {stats['failed']}")
        logger.info(f"By category: {dict(stats['by_category'])}")
        
    finally:
        # Close browser
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if playwright_context:
            try:
                playwright_context.__exit__(None, None, None)
            except Exception:
                pass
    
    return stats


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
    
    # Batch URLs command
    batch_urls_parser = subparsers.add_parser('batch-urls', help='Process URLs from file and categorize by screen type')
    batch_urls_parser.add_argument('--url-file', default='url.md', help='Path to file containing URLs (default: url.md)')
    batch_urls_parser.add_argument('--output-dir', default='.', help='Output directory for categorized templates (default: current directory)')
    batch_urls_parser.add_argument('--browser-path', help='Path to Chromium/Chrome executable')
    
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
            
        elif args.command == 'batch-urls':
            stats = process_urls_batch(
                args.url_file,
                args.output_dir,
                args.browser_path,
            )
            print(json.dumps(stats, indent=2))
            
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        raise


if __name__ == '__main__':
    main()

