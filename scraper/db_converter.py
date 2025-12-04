"""Convert scraped templates to FlowRunner format and save to database."""

import os
import json
import logging
from typing import Dict, Optional, List, Any

logger = logging.getLogger(__name__)

try:
    import psycopg2
    from psycopg2.extras import Json
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    logger.warning("psycopg2 not available. Database saving will be disabled. Install with: pip install psycopg2-binary")


def normalize_bbox(bbox: Dict[str, float], viewport: Dict[str, float]) -> Dict[str, float]:
    """Convert normalized bounding box (0-1) to pixel coordinates."""
    return {
        'x': bbox['x'] * viewport['width'],
        'y': bbox['y'] * viewport['height'],
        'width': bbox['width'] * viewport['width'],
        'height': bbox['height'] * viewport['height'],
    }


def map_role(role: str) -> Optional[str]:
    """Map scraped role to FlowRunner Role type."""
    role_map = {
        'header': 'header',
        'body': 'body',
        'footer': 'footer',
        'sidebar': 'sidebar',
        'navigation': 'navigation',
        'main': 'main',
        'aside': 'aside',
        'content': 'body',  # Map 'content' to 'body'
        'image': 'body',  # Map 'image' role to 'body'
    }
    return role_map.get(role.lower())


def convert_scraped_template(scraped: Dict, template_name: Optional[str] = None) -> Dict:
    """
    Convert scraped template format to FlowRunner Template format.
    
    Args:
        scraped: Scraped template dictionary
        template_name: Optional display name for the template
        
    Returns:
        FlowRunner template dictionary
    """
    viewport = scraped.get('viewport', {'width': 1280, 'height': 720})
    slots_map = {slot['id']: slot for slot in scraped.get('slots', [])}
    
    # Convert sections
    sections = []
    for section in scraped.get('sections', []):
        # Get all slots for this section
        section_slots = []
        for slot_id in section.get('slotIds', []):
            scraped_slot = slots_map.get(slot_id)
            if not scraped_slot:
                continue
            
            slot_type = 'image' if scraped_slot['type'] == 'image' else 'content'
            role = map_role(scraped_slot.get('role', 'content'))
            
            section_slots.append({
                'id': scraped_slot['id'],
                'type': slot_type,
                'role': role,
                'bbox': normalize_bbox(scraped_slot['boundingBox'], viewport),
            })
        
        # Calculate section bounding box from its slots
        if section_slots:
            section_bbox = {
                'x': min(slot['bbox']['x'] for slot in section_slots),
                'y': min(slot['bbox']['y'] for slot in section_slots),
                'width': max(slot['bbox']['x'] + slot['bbox']['width'] for slot in section_slots) - 
                        min(slot['bbox']['x'] for slot in section_slots),
                'height': max(slot['bbox']['y'] + slot['bbox']['height'] for slot in section_slots) - 
                         min(slot['bbox']['y'] for slot in section_slots),
            }
        else:
            section_bbox = {'x': 0, 'y': 0, 'width': viewport['width'], 'height': viewport['height']}
        
        # Handle repeated groups if present
        repeated_groups = []
        grouping = scraped.get('grouping', {})
        repeated_groups_data = grouping.get('repeatedGroups', {})
        
        for group_id, group_data in repeated_groups_data.items():
            group_slots = []
            if group_data.get('items'):
                for item in group_data['items']:
                    for slot_id in item.get('slotIds', []):
                        scraped_slot = slots_map.get(slot_id)
                        if scraped_slot:
                            slot_type = 'image' if scraped_slot['type'] == 'image' else 'content'
                            role = map_role(scraped_slot.get('role', 'content'))
                            group_slots.append({
                                'id': scraped_slot['id'],
                                'type': slot_type,
                                'role': role,
                                'bbox': normalize_bbox(scraped_slot['boundingBox'], viewport),
                            })
            
            if group_slots:
                repeated_groups.append({
                    'id': group_id,
                    'slots': group_slots,
                    'minItems': group_data.get('count', 2),
                    'maxItems': group_data.get('count'),
                })
        
        section_role = map_role(section.get('role', 'content'))
        sections.append({
            'id': section['id'],
            'role': section_role,
            'bbox': section_bbox,
            'slots': section_slots,
            'repeatedGroups': repeated_groups if repeated_groups else None,
        })
    
    # Map screen type
    screen_type = scraped.get('screenType', 'page')
    if screen_type == 'page':
        screen_type = 'landing'
    
    # Generate template name if not provided
    if not template_name:
        template_name = f"Scraped {screen_type.title()} Template"
    
    return {
        'id': scraped.get('id', 'component-001'),
        'name': template_name,
        'screenType': screen_type,
        'pattern': f"scraped-{scraped.get('id', 'component-001')}",
        'sections': sections,
        'metadata': {
            'description': f"Template scraped from website ({viewport['width']}x{viewport['height']})",
            'version': '1.0.0',
        },
    }


def save_template_to_db(template: Dict, database_url: Optional[str] = None) -> bool:
    """
    Save template to PostgreSQL database.
    
    Args:
        template: FlowRunner template dictionary
        database_url: PostgreSQL connection string (or from DATABASE_URL env var)
        
    Returns:
        True if successful, False otherwise
    """
    if not PSYCOPG2_AVAILABLE:
        logger.error("psycopg2 not available. Cannot save to database.")
        return False
    
    if not database_url:
        database_url = os.getenv('DATABASE_URL')
    
    if not database_url:
        logger.error("DATABASE_URL not set. Cannot save to database.")
        return False
    
    try:
        # Parse DATABASE_URL and connect
        conn = psycopg2.connect(database_url)
        cur = conn.cursor()
        
        # Upsert template (using NOW() for timestamps to match Prisma behavior)
        cur.execute("""
            INSERT INTO templates (id, name, "screenType", pattern, "templateJson", "createdAt", "updatedAt")
            VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                "screenType" = EXCLUDED."screenType",
                pattern = EXCLUDED.pattern,
                "templateJson" = EXCLUDED."templateJson",
                "updatedAt" = NOW()
        """, (
            template['id'],
            template['name'],
            template['screenType'],
            template.get('pattern'),
            Json(template),  # Store entire template as JSON
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"✓ Template saved to database: {template['id']} ({template['name']})")
        return True
        
    except Exception as e:
        logger.error(f"Error saving template to database: {str(e)}")
        return False


def convert_and_save(scraped_template: Dict, 
                    template_name: Optional[str] = None,
                    database_url: Optional[str] = None,
                    save_to_db: bool = True) -> Optional[Dict]:
    """
    Convert scraped template and optionally save to database.
    
    Args:
        scraped_template: Scraped template dictionary
        template_name: Optional display name
        database_url: Optional database URL (or from DATABASE_URL env var)
        save_to_db: Whether to save to database (default: True)
        
    Returns:
        Converted FlowRunner template dictionary, or None if conversion failed
    """
    try:
        converted = convert_scraped_template(scraped_template, template_name)
        
        if save_to_db:
            save_template_to_db(converted, database_url)
        
        return converted
        
    except Exception as e:
        logger.error(f"Error converting template: {str(e)}")
        return None

