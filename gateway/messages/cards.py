"""Neonize card types shared by validation and builders."""
from neonize.ext.interactive_message import (
    Post as AIRichPost,
    Product as AIRichProduct,
    Reel as AIRichReel,
    Source as AIRichSource,
)


AIRICH_CARDS = {
    "source": AIRichSource,
    "product": AIRichProduct,
    "reels": AIRichReel,
    "post": AIRichPost,
}
