"""Layout analysis for extracting visual structure, bounding boxes, and semantic roles."""

import logging
from typing import Dict, List, Optional, Set
from collections import defaultdict
from dataclasses import dataclass

from playwright.sync_api import Page

logger = logging.getLogger(__name__)


@dataclass
class ElementInfo:
    """Information about a DOM element."""
    tag: str
    bounding_box: Dict[str, float]
    text_content: str
    class_names: List[str]
    id: Optional[str]
    role: Optional[str]
    element_type: str  # 'image', 'text', 'container', 'mixed'
    is_visible: bool
    has_children: bool
    computed_styles: Dict[str, str]
    animations: Optional[Dict[str, any]] = None
    component_info: Optional[Dict[str, any]] = None


@dataclass
class Slot:
    """A layout slot (text, image, or container)."""
    id: str
    type: str  # 'text', 'image', 'container'
    role: str
    bounding_box: Dict[str, float]
    aspect: Optional[str] = None
    repeated: bool = False
    repeated_index: Optional[int] = None
    animations: Optional[Dict[str, any]] = None
    component_info: Optional[Dict[str, any]] = None


@dataclass
class Section:
    """A layout section."""
    id: str
    role: str
    layout_hints: Dict[str, any]
    slot_ids: List[str]
    animations: Optional[List[Dict[str, any]]] = None
    components: Optional[List[Dict[str, any]]] = None


def _detect_animations(page: Page, element_handle) -> Optional[Dict[str, any]]:
    """Detect CSS animations and transitions on an element."""
    try:
        animation_data = element_handle.evaluate("""
            el => {
                const style = window.getComputedStyle(el);
                const animations = {
                    animation: style.animation || style.webkitAnimation || null,
                    animationName: style.animationName || style.webkitAnimationName || null,
                    animationDuration: style.animationDuration || style.webkitAnimationDuration || null,
                    animationTimingFunction: style.animationTimingFunction || style.webkitAnimationTimingFunction || null,
                    animationDelay: style.animationDelay || style.webkitAnimationDelay || null,
                    animationIterationCount: style.animationIterationCount || style.webkitAnimationIterationCount || null,
                    animationDirection: style.animationDirection || style.webkitAnimationDirection || null,
                    transition: style.transition || style.webkitTransition || null,
                    transitionProperty: style.transitionProperty || style.webkitTransitionProperty || null,
                    transitionDuration: style.transitionDuration || style.webkitTransitionDuration || null,
                    transitionTimingFunction: style.transitionTimingFunction || style.webkitTransitionTimingFunction || null,
                    transform: style.transform || style.webkitTransform || null,
                };
                
                // Check if element has any animations or transitions
                const hasAnimation = animation_data.animation && 
                                    animation_data.animation !== 'none' && 
                                    animation_data.animation !== '';
                const hasTransition = animation_data.transition && 
                                     animation_data.transition !== 'none' && 
                                     animation_data.transition !== '';
                const hasTransform = animation_data.transform && 
                                    animation_data.transform !== 'none' && 
                                    animation_data.transform !== '';
                
                if (!hasAnimation && !hasTransition && !hasTransform) {
                    return null;
                }
                
                // Clean up null values
                const cleaned = {};
                for (const [key, value] of Object.entries(animation_data)) {
                    if (value && value !== 'none' && value !== '') {
                        cleaned[key] = value;
                    }
                }
                
                return Object.keys(cleaned).length > 0 ? cleaned : null;
            }
        """)
        return animation_data
    except Exception as e:
        logger.debug(f"Error detecting animations: {e}")
        return None


def _detect_component(element_handle) -> Optional[Dict[str, any]]:
    """Detect component information from element attributes."""
    try:
        component_data = element_handle.evaluate("""
            el => {
                const data = {};
                
                // Check for React component indicators
                const reactKey = el.getAttribute('data-reactroot') || 
                                el.getAttribute('data-react-component') ||
                                el.getAttribute('data-component');
                if (reactKey) {
                    data.reactComponent = true;
                    data.componentId = reactKey;
                }
                
                // Check for data attributes that might indicate components
                const dataAttrs = {};
                for (let attr of el.attributes) {
                    if (attr.name.startsWith('data-')) {
                        const key = attr.name.replace('data-', '');
                        // Skip common data attributes that aren't component-related
                        if (!['testid', 'id', 'cy', 'qa'].includes(key)) {
                            dataAttrs[key] = attr.value;
                        }
                    }
                }
                if (Object.keys(dataAttrs).length > 0) {
                    data.dataAttributes = dataAttrs;
                }
                
                // Check for component-like class patterns
                const classList = Array.from(el.classList || []);
                const componentClasses = classList.filter(cls => 
                    cls.includes('component') || 
                    cls.includes('widget') || 
                    cls.match(/^[A-Z][a-zA-Z]*$/) // PascalCase classes often indicate components
                );
                if (componentClasses.length > 0) {
                    data.componentClasses = componentClasses;
                }
                
                // Check for Vue component indicators
                if (el.hasAttribute('data-v-')) {
                    data.vueComponent = true;
                }
                
                // Check for Angular component indicators
                if (el.hasAttribute('ng-version') || el.hasAttribute('_ngcontent')) {
                    data.angularComponent = true;
                }
                
                return Object.keys(data).length > 0 ? data : null;
            }
        """)
        return component_data
    except Exception as e:
        logger.debug(f"Error detecting component: {e}")
        return None


def _gcd(a: int, b: int) -> int:
    """Calculate greatest common divisor."""
    while b:
        a, b = b, a % b
    return a


def _simplify_ratio(width: float, height: float, tolerance: float = 0.01) -> Optional[str]:
    """Simplify aspect ratio to common format like '16:9'."""
    if height == 0:
        return None
    
    ratio = width / height
    
    # Common aspect ratios
    common_ratios = [
        (1, 1, "1:1"),
        (4, 3, "4:3"),
        (16, 9, "16:9"),
        (16, 10, "16:10"),
        (21, 9, "21:9"),
        (3, 2, "3:2"),
        (2, 1, "2:1"),
    ]
    
    for w, h, label in common_ratios:
        if abs(ratio - (w / h)) < tolerance:
            return label
    
    # Try to find a simplified ratio
    max_denom = 20
    best_match = None
    best_diff = float('inf')
    
    for denom in range(1, max_denom + 1):
        num = round(ratio * denom)
        if num == 0:
            continue
        actual_ratio = num / denom
        diff = abs(ratio - actual_ratio)
        if diff < best_diff and diff < tolerance:
            best_diff = diff
            best_match = f"{num}:{denom}"
    
    return best_match


def _get_element_info(page: Page, element_handle) -> Optional[ElementInfo]:
    """Extract information about an element."""
    try:
        # Get basic properties
        tag = element_handle.evaluate("el => el.tagName.toLowerCase()")
        bounding_box = element_handle.bounding_box()
        
        if not bounding_box or bounding_box['width'] == 0 or bounding_box['height'] == 0:
            return None
        
        # Get text content
        text_content = element_handle.evaluate("el => el.textContent || ''").strip()
        
        # Get class names
        class_names = element_handle.evaluate(
            "el => Array.from(el.classList || [])"
        ) or []
        
        # Get ID
        element_id = element_handle.evaluate("el => el.id || null")
        
        # Get role
        role_attr = element_handle.evaluate("el => el.getAttribute('role') || null")
        
        # Check visibility
        is_visible = element_handle.evaluate(
            "el => { const style = window.getComputedStyle(el); "
            "return style.display !== 'none' && style.visibility !== 'hidden' && "
            "style.opacity !== '0' && el.offsetWidth > 0 && el.offsetHeight > 0; }"
        )
        
        if not is_visible:
            return None
        
        # Check for children
        has_children = element_handle.evaluate("el => el.children.length > 0")
        
        # Get computed styles for layout hints (including background image)
        computed_styles = element_handle.evaluate("""
            el => {
                const style = window.getComputedStyle(el);
                return {
                    display: style.display,
                    flexDirection: style.flexDirection,
                    gridTemplateColumns: style.gridTemplateColumns,
                    gap: style.gap,
                    alignItems: style.alignItems,
                    justifyContent: style.justifyContent,
                    backgroundImage: style.backgroundImage,
                };
            }
        """) or {}

        # Detect animations and components
        animations = _detect_animations(page, element_handle)
        component_info = _detect_component(element_handle)

        # Determine element type
        class_str = ' '.join(class_names).lower()
        bg_image_style = computed_styles.get('backgroundImage', '') or ''
        has_bg_image = bool(bg_image_style and bg_image_style != 'none')

        element_type = 'container'
        if tag in ['img', 'picture', 'svg']:
            element_type = 'image'
        elif has_bg_image or any(token in class_str for token in ['bg-cover', 'bg-image', 'bg-img', 'hero-image']):
            # Treat containers with background images or common bg-image utility classes as images
            element_type = 'image'
        elif tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'span', 'a', 'button', 'label']:
            element_type = 'text'
        
        return ElementInfo(
            tag=tag,
            bounding_box={
                'x': bounding_box['x'],
                'y': bounding_box['y'],
                'width': bounding_box['width'],
                'height': bounding_box['height'],
            },
            text_content=text_content,
            class_names=class_names,
            id=element_id,
            role=role_attr,
            element_type=element_type,
            is_visible=is_visible,
            has_children=has_children,
            computed_styles=computed_styles,
            animations=animations,
            component_info=component_info,
        )
    except Exception as e:
        logger.debug(f"Error extracting element info: {e}")
        return None


def _infer_semantic_role(element: ElementInfo, position_in_viewport: float, 
                         is_large: bool, has_headline: bool) -> str:
    """Infer semantic role from element properties."""
    tag = element.tag
    class_str = ' '.join(element.class_names).lower()
    text_lower = element.text_content.lower()
    
    # Hero detection
    if ('hero' in class_str or 'hero' in text_lower or 
        (position_in_viewport < 0.3 and is_large and has_headline)):
        return 'hero-split' if element.has_children else 'hero'
    
    # Card detection
    if ('card' in class_str or 'card' in text_lower):
        return 'card-item'
    
    # Grid detection
    if ('grid' in class_str or element.computed_styles.get('display') == 'grid'):
        return 'card-grid'
    
    # Navigation
    if tag == 'nav' or 'nav' in class_str or element.role == 'navigation':
        return 'navigation'
    
    # Headline
    if tag in ['h1', 'h2', 'h3']:
        return 'headline'
    
    # Subhead
    if tag in ['h4', 'h5', 'h6']:
        return 'subhead'
    
    # CTA/Button
    if tag in ['button', 'a'] and ('cta' in class_str or 'button' in class_str):
        return 'cta'
    
    # Image roles
    if element.element_type == 'image':
        if position_in_viewport < 0.3:
            return 'hero-image'
        return 'image'
    
    # Default
    return 'content-block'


def _detect_repeated_groups(elements: List[ElementInfo], 
                            threshold: float = 0.1) -> Dict[int, List[int]]:
    """Detect groups of repeated elements (e.g., cards in a grid)."""
    groups: Dict[int, List[int]] = {}
    processed: Set[int] = set()
    
    for i, elem1 in enumerate(elements):
        if i in processed:
            continue
        
        group = [i]
        w1, h1 = elem1.bounding_box['width'], elem1.bounding_box['height']
        
        for j, elem2 in enumerate(elements[i+1:], start=i+1):
            if j in processed:
                continue
            
            w2, h2 = elem2.bounding_box['width'], elem2.bounding_box['height']
            
            # Check if dimensions are similar
            width_diff = abs(w1 - w2) / max(w1, w2) if max(w1, w2) > 0 else 1.0
            height_diff = abs(h1 - h2) / max(h1, h2) if max(h1, h2) > 0 else 1.0
            
            if width_diff < threshold and height_diff < threshold:
                group.append(j)
                processed.add(j)
        
        if len(group) > 1:
            groups[i] = group
            processed.add(i)
    
    return groups


def _detect_grid_layout(slots: List[Slot]) -> Optional[Dict[str, any]]:
    """Detect grid layout properties from slot positions (normalized 0-1)."""
    if len(slots) < 2:
        return None

    # Group slots by similar Y position (same visual row)
    y_groups: Dict[float, List[Slot]] = defaultdict(list)
    tolerance = 0.05  # normalized units (~5% of viewport height)

    for slot in slots:
        y = round(slot.bounding_box['y'] / tolerance) * tolerance
        y_groups[y].append(slot)

    if not y_groups:
        return None

    # Take the row with the most slots as the representative grid row
    _, row_slots = max(y_groups.items(), key=lambda x: len(x[1]))
    if len(row_slots) < 2:
        return None

    # Sort by X position
    row_slots.sort(key=lambda s: s.bounding_box['x'])

    # Calculate gaps between slots in that row
    gaps: List[float] = []
    for i in range(len(row_slots) - 1):
        right = row_slots[i].bounding_box['x'] + row_slots[i].bounding_box['width']
        gap = row_slots[i+1].bounding_box['x'] - right
        if gap > 0:
            gaps.append(gap)

    avg_gap = sum(gaps) / len(gaps) if gaps else 0.0

    return {
        'displayType': 'grid',
        'gridColumns': len(row_slots),
        'gap': round(avg_gap, 3),
        'alignment': 'center',
    }


def _normalize_role(role: str) -> str:
    """Normalize role names to a standard set."""
    role_lower = role.lower()
    
    # Hero variations
    if role_lower in ['hero', 'hero-split', 'hero-section']:
        return 'hero'
    
    # Card variations
    if role_lower in ['card', 'card-item', 'card-grid']:
        if 'grid' in role_lower:
            return 'card-grid'
        return 'card'
    
    # Content variations
    if role_lower in ['content', 'content-block', 'content-section', 'content-area']:
        return 'content'
    
    # Navigation variations
    if role_lower in ['nav', 'navigation', 'navbar', 'menu']:
        return 'navigation'
    
    # Text variations
    if role_lower in ['headline', 'heading', 'title', 'h1', 'h2', 'h3']:
        return 'headline'
    if role_lower in ['subhead', 'subheading', 'subtitle', 'h4', 'h5', 'h6']:
        return 'subhead'
    if role_lower in ['body', 'paragraph', 'text', 'p']:
        return 'body-text'
    
    # Image variations
    if role_lower in ['image', 'img', 'picture', 'photo']:
        return 'image'
    if role_lower in ['hero-image', 'hero-img']:
        return 'hero-image'
    
    # CTA variations
    if role_lower in ['cta', 'button', 'call-to-action', 'action']:
        return 'cta'
    
    # Footer variations
    if role_lower in ['footer', 'foot']:
        return 'footer'
    
    # Default
    return role_lower if role_lower else 'content'


def _normalize_bounding_box(bbox: Dict[str, float], viewport_width: float, viewport_height: float) -> Dict[str, float]:
    """Normalize bounding box to relative coordinates (0-1 range)."""
    if viewport_width == 0 or viewport_height == 0:
        return bbox
    
    return {
        'x': round(bbox['x'] / viewport_width, 4),
        'y': round(bbox['y'] / viewport_height, 4),
        'width': round(bbox['width'] / viewport_width, 4),
        'height': round(bbox['height'] / viewport_height, 4),
    }


def _detect_visual_groups(slots: List[Slot], threshold: float = 0.02) -> Dict[str, List[str]]:
    """Detect visual groups based on proximity and alignment (using normalized coordinates)."""
    groups: Dict[str, List[str]] = {}
    processed: Set[str] = set()
    group_counter = 0
    
    for i, slot1 in enumerate(slots):
        if slot1.id in processed:
            continue
        
        group = [slot1.id]
        processed.add(slot1.id)
        
        for slot2 in slots[i+1:]:
            if slot2.id in processed:
                continue
            
            # Check proximity (normalized coordinates, 0-1 range)
            x_diff = abs(slot1.bounding_box['x'] - slot2.bounding_box['x'])
            y_diff = abs(slot1.bounding_box['y'] - slot2.bounding_box['y'])
            
            # Check if aligned horizontally or vertically (within threshold)
            horizontal_aligned = y_diff < threshold
            vertical_aligned = x_diff < threshold
            # Check if close together (within threshold distance)
            close_proximity = (x_diff + y_diff) < threshold * 3
            
            # Group if aligned/close and same role, or if very close regardless of role
            if (horizontal_aligned or vertical_aligned or close_proximity) and \
               (slot1.role == slot2.role or close_proximity):
                group.append(slot2.id)
                processed.add(slot2.id)
        
        if len(group) > 1:
            group_id = f"group-{group_counter}"
            groups[group_id] = group
            group_counter += 1
    
    return groups


def _generate_pattern_summary(sections: List[Section], slots: List[Slot]) -> Dict[str, any]:
    """Generate a high-level pattern summary of the screen."""
    section_roles = [s.role for s in sections]
    slot_roles = [s.role for s in slots]
    
    # Pattern sequence
    pattern_sequence = []
    for section in sections:
        normalized_role = _normalize_role(section.role)
        if normalized_role not in pattern_sequence or pattern_sequence[-1] != normalized_role:
            pattern_sequence.append(normalized_role)
    
    # Key features
    features = {
        'hasNavigation': any('navigation' in _normalize_role(r) for r in slot_roles),
        'hasHero': any('hero' in _normalize_role(r) for r in section_roles),
        'hasCardGrid': any('card-grid' in _normalize_role(r) for r in section_roles),
        'hasFooter': any('footer' in _normalize_role(r) for r in slot_roles),
        'hasImages': any(s.type == 'image' for s in slots),
        'hasRepeatedGroups': any(s.repeated for s in slots),
    }
    
    # Pattern type
    pattern_type = '-'.join(pattern_sequence[:5])  # Limit to first 5 sections
    if not pattern_type:
        pattern_type = 'unknown'
    
    # Dominant layout
    layout_types = {}
    for section in sections:
        display_type = section.layout_hints.get('displayType', 'flex')
        layout_types[display_type] = layout_types.get(display_type, 0) + 1
    
    dominant_layout = max(layout_types.items(), key=lambda x: x[1])[0] if layout_types else 'flex'
    
    return {
        'patternType': pattern_type,
        'patternSequence': pattern_sequence,
        'sectionCount': len(sections),
        'slotCount': len(slots),
        'features': features,
        'dominantLayout': dominant_layout,
        'layoutDistribution': layout_types,
    }


def _infer_screen_type(elements: List[ElementInfo], sections: List[Section]) -> str:
    """Infer screen type from layout and textual clues."""
    roles = [s.role for s in sections]
    class_str = ' '.join([' '.join(e.class_names) for e in elements]).lower()
    text_str = ' '.join([e.text_content or '' for e in elements]).lower()

    # Auth / sign-in / sign-up screens
    auth_keywords = [
        'sign in', 'sign-in', 'signin',
        'log in', 'login', 'log-in',
        'password', 'email',
        'create account', 'sign up', 'signup', 'sign-up',
    ]
    if any(k in text_str for k in auth_keywords) or any(k in class_str for k in ['signin', 'login', 'auth']):
        return 'auth'

    if 'service' in class_str or any('service' in r for r in roles):
        return 'services'
    if 'pricing' in class_str or any('pricing' in r for r in roles):
        return 'pricing'
    if 'portfolio' in class_str or any('portfolio' in r for r in roles):
        return 'portfolio'
    if 'blog' in class_str or 'article' in class_str:
        return 'blog'
    if 'landing' in class_str or any('hero' in r for r in roles):
        return 'landing'
    
    # Dashboard detection
    dashboard_keywords = [
        'dashboard', 'analytics', 'metrics', 'admin', 'admin-panel', 
        'control-panel', 'admin panel', 'control panel'
    ]
    if any(k in text_str for k in dashboard_keywords) or any(k in class_str for k in dashboard_keywords):
        return 'dashboard'

    return 'page'


def analyze_layout(page: Page, component_id: Optional[str] = None, 
                   component_name: Optional[str] = None) -> Dict:
    """
    Analyze the layout of a page and extract structure information.
    
    Args:
        page: Playwright page object
        component_id: Optional component identifier
        component_name: Optional component name
        
    Returns:
        Dictionary with layout structure matching the specified format
    """
    try:
        logger.info("Starting layout analysis...")
        
        # Wait for page to be ready
        page.wait_for_load_state('networkidle', timeout=30000)
        page.wait_for_timeout(1000)
        
        # Get viewport size
        viewport = page.viewport_size
        viewport_width = viewport['width'] if viewport else 1920
        viewport_height = viewport['height'] if viewport else 1000
        
        # Get all elements using a query selector that excludes non-rendered elements
        # We'll filter by tag in the extraction function
        excluded_tags = {'script', 'style', 'meta', 'link', 'noscript', 'template', 'head', 'html'}
        all_elements_handles = page.locator('body *').all()
        
        # Limit to first 1000 elements for performance
        all_elements_handles = all_elements_handles[:1000]
        logger.info(f"Found {len(all_elements_handles)} elements to analyze")
        
        # Extract element information
        elements: List[ElementInfo] = []
        for handle in all_elements_handles:
            try:
                # Quick tag check before full extraction
                tag = handle.evaluate("el => el.tagName.toLowerCase()")
                if tag in excluded_tags:
                    continue
                    
                info = _get_element_info(page, handle)
                if info:
                    elements.append(info)
            except Exception as e:
                logger.debug(f"Skipping element due to error: {e}")
                continue
        
        logger.info(f"Extracted {len(elements)} visible elements")
        
        if not elements:
            return {
                'id': component_id or 'unknown',
                'screenType': 'page',
                'viewport': {'width': viewport_width, 'height': viewport_height},
                'patternSummary': {
                    'patternType': 'empty',
                    'patternSequence': [],
                    'sectionCount': 0,
                    'slotCount': 0,
                    'features': {},
                    'dominantLayout': 'flex',
                    'layoutDistribution': {},
                },
                'grouping': {
                    'repeatedGroups': {},
                    'visualGroups': {},
                    'groupCount': 0,
                },
                'sections': [],
                'slots': [],
            }
        
        # Filter to significant elements (min size threshold)
        min_size = 20  # pixels
        significant_elements = [
            e for e in elements
            if e.bounding_box['width'] >= min_size and e.bounding_box['height'] >= min_size
        ]
        
        # Detect repeated groups
        repeated_groups = _detect_repeated_groups(significant_elements)
        
        # Create slots
        slots: List[Slot] = []
        slot_counter = 0
        
        # Map slot IDs to elements for later reference
        slot_to_element: Dict[str, ElementInfo] = {}
        
        # Track which elements are in repeated groups
        in_repeated_group: Set[int] = set()
        for group in repeated_groups.values():
            in_repeated_group.update(group)
        
        for i, element in enumerate(significant_elements):
            # Skip if element is too small or not meaningful
            if element.bounding_box['width'] < 50 and element.bounding_box['height'] < 50:
                # Only skip if it's not text
                if element.element_type != 'text':
                    continue
            
            # Determine position in viewport
            position_ratio = element.bounding_box['y'] / viewport_height if viewport_height > 0 else 0.5
            
            # Check if large
            is_large = (element.bounding_box['width'] > 300 or 
                       element.bounding_box['height'] > 200)

            # Skip full-page container wrappers (background/layout shells)
            if (
                element.element_type == 'container'
                and element.has_children
                and element.bounding_box['width'] >= viewport_width * 0.9
                and element.bounding_box['height'] >= viewport_height * 0.7
            ):
                continue
            
            # Check for headline
            has_headline = (
                element.tag in ['h1', 'h2', 'h3']
                or any('headline' in c.lower() for c in element.class_names)
            )
            
            # Infer role
            role = _infer_semantic_role(element, position_ratio, is_large, has_headline)
            # Normalize role
            normalized_role = _normalize_role(role)
            
            # Determine slot type
            slot_type = element.element_type
            if slot_type == 'container' and element.has_children:
                slot_type = 'container'
            elif element.element_type == 'text' and element.tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p']:
                slot_type = 'text'
            elif element.element_type == 'image':
                slot_type = 'image'
            else:
                # Skip non-significant containers
                if not element.text_content and not element.has_children:
                    continue
                slot_type = 'container'
            
            # Generate slot ID
            slot_id = f"slot-{role}-{slot_counter}"
            if element.id:
                slot_id = f"slot-{element.id}"
            slot_counter += 1
            
            # Calculate aspect ratio
            aspect = None
            if slot_type == 'image':
                aspect = _simplify_ratio(
                    element.bounding_box['width'],
                    element.bounding_box['height']
                )
            
            # Check if repeated
            is_repeated = i in in_repeated_group
            repeated_index = None
            if is_repeated:
                for group_idx, group in repeated_groups.items():
                    if i in group:
                        repeated_index = group.index(i)
                        break
            
            # Normalize bounding box
            normalized_bbox = _normalize_bounding_box(
                element.bounding_box,
                viewport_width,
                viewport_height
            )
            
            slot = Slot(
                id=slot_id,
                type=slot_type,
                role=normalized_role,
                bounding_box=normalized_bbox,
                aspect=aspect,
                repeated=is_repeated,
                repeated_index=repeated_index,
                animations=element.animations,
                component_info=element.component_info,
            )
            slots.append(slot)
            slot_to_element[slot_id] = element
        
        # Group slots into sections
        sections: List[Section] = []
        section_counter = 0
        
        # Group by Y position (sections are typically stacked vertically)
        # Use normalized coordinates (0-1) with a tolerance of ~10% viewport height
        y_sections: Dict[float, List[Slot]] = defaultdict(list)
        tolerance = 0.1  # normalized units

        for slot in slots:
            y = round(slot.bounding_box['y'] / tolerance) * tolerance
            y_sections[y].append(slot)
        
        # Create sections from Y groups
        for y_pos, section_slots in sorted(y_sections.items()):
            if not section_slots:
                continue
            
            # Determine section role
            section_roles = [s.role for s in section_slots]
            if 'hero' in ' '.join(section_roles):
                section_role = 'hero' if len(section_slots) <= 2 else 'hero'
            elif any('card' in r for r in section_roles):
                section_role = 'card-grid'
            elif any('grid' in r for r in section_roles):
                section_role = 'card-grid'
            else:
                section_role = 'content'
            
            # Normalize section role
            section_role = _normalize_role(section_role)
            
            # Detect grid layout for this section based on slot positions
            layout_hints = _detect_grid_layout(section_slots) or {
                'displayType': 'flex',
                'flexDirection': 'column',
                'gap': 24,
                'alignment': 'start',
            }
            
            section_id = f"section-{section_role}-{section_counter}"
            section_counter += 1
            
            # Aggregate animations and components for this section
            section_animations: List[Dict[str, any]] = []
            section_components: List[Dict[str, any]] = []
            
            for slot in section_slots:
                # Collect unique animations from slots in this section
                if slot.animations:
                    animation_entry = {
                        'slotId': slot.id,
                        'animation': slot.animations,
                    }
                    section_animations.append(animation_entry)
                
                # Collect unique components from slots in this section
                if slot.component_info:
                    component_entry = {
                        'slotId': slot.id,
                        'component': slot.component_info,
                    }
                    section_components.append(component_entry)
            
            section = Section(
                id=section_id,
                role=section_role,
                layout_hints=layout_hints,
                slot_ids=[s.id for s in section_slots],
                animations=section_animations if section_animations else None,
                components=section_components if section_components else None,
            )
            sections.append(section)
        
        # Infer screen type
        screen_type = _infer_screen_type(significant_elements, sections)
        
        # Detect visual groups
        visual_groups = _detect_visual_groups(slots)
        
        # Generate grouping metadata
        grouping_metadata = {
            'repeatedGroups': {},
            'visualGroups': visual_groups,
            'groupCount': len(visual_groups),
        }
        
        # Build repeated groups metadata - group by role and index
        repeated_by_role: Dict[str, Dict[int, List[str]]] = defaultdict(lambda: defaultdict(list))
        for slot in slots:
            if slot.repeated and slot.repeated_index is not None:
                repeated_by_role[slot.role][slot.repeated_index].append(slot.id)
        
        # Convert to final structure
        for role, indices in repeated_by_role.items():
            group_key = f"repeated-{role}"
            grouping_metadata['repeatedGroups'][group_key] = {
                'role': role,
                'count': len(indices),
                'items': [
                    {
                        'index': idx,
                        'slotIds': slot_ids,
                    }
                    for idx, slot_ids in sorted(indices.items())
                ],
            }
        
        # Generate pattern summary
        pattern_summary = _generate_pattern_summary(sections, slots)
        
        # Generate component ID
        final_id = component_id or component_name or 'component-001'
        if component_name:
            final_id = component_name.lower().replace(' ', '-').replace('_', '-')
        
        # Build output
        result = {
            'id': final_id,
            'screenType': screen_type,
            'viewport': {
                'width': viewport_width,
                'height': viewport_height,
            },
            'patternSummary': pattern_summary,
            'grouping': grouping_metadata,
            'sections': [
                {
                    'id': s.id,
                    'role': s.role,
                    'layoutHints': s.layout_hints,
                    'slotIds': s.slot_ids,
                    **({'animations': s.animations} if s.animations else {}),
                    **({'components': s.components} if s.components else {}),
                }
                for s in sections
            ],
            'slots': [
                {
                    'id': s.id,
                    'type': s.type,
                    'role': s.role,
                    'boundingBox': s.bounding_box,
                    **({'aspect': s.aspect} if s.aspect else {}),
                    **({'repeated': s.repeated, 'repeatedIndex': s.repeated_index} 
                       if s.repeated else {}),
                    **({'animations': s.animations} if s.animations else {}),
                    **({'componentInfo': s.component_info} if s.component_info else {}),
                }
                for s in slots
            ],
        }
        
        logger.info(f"Layout analysis complete: {len(sections)} sections, {len(slots)} slots")
        return result
        
    except Exception as e:
        logger.error(f"Error during layout analysis: {str(e)}")
        return {
            'id': component_id or 'unknown',
            'screenType': 'page',
            'viewport': {'width': 1920, 'height': 1000},
            'patternSummary': {
                'patternType': 'unknown',
                'patternSequence': [],
                'sectionCount': 0,
                'slotCount': 0,
                'features': {},
                'dominantLayout': 'flex',
                'layoutDistribution': {},
            },
            'grouping': {
                'repeatedGroups': {},
                'visualGroups': {},
                'groupCount': 0,
            },
            'sections': [],
            'slots': [],
            'error': str(e),
        }

