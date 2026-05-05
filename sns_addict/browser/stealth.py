"""Extra stealth patches applied after context launch."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def apply_extra_stealth(context) -> None:
    """Apply navigator.language + WebGL fingerprint weakening."""
    await context.add_init_script("""
        // Force ko-KR language
        Object.defineProperty(navigator, 'language', {get: () => 'ko-KR'});
        Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko', 'en-US']});

        // Weaken WebGL fingerprint
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Intel Inc.';
            if (parameter === 37446) return 'Intel Iris OpenGL Engine';
            return getParameter.call(this, parameter);
        };
    """)
    logger.debug("Extra stealth patches applied")
