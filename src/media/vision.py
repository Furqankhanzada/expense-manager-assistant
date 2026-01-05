"""Image and document processing for expense extraction."""

import io
import logging
from typing import BinaryIO

from PIL import Image

from src.llm.expense_parser import ParsedReceipt, parse_receipt_image
from src.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

# Supported image formats
SUPPORTED_IMAGE_FORMATS = {"image/jpeg", "image/png", "image/webp", "image/gif"}

# Max image size for processing (to avoid API limits)
MAX_IMAGE_SIZE = (1920, 1920)
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


def optimize_image(image_data: bytes, mime_type: str = "image/jpeg") -> tuple[bytes, str]:
    """Optimize image for LLM processing.

    Returns:
        Tuple of (optimized_bytes, mime_type)
    """
    try:
        img = Image.open(io.BytesIO(image_data))

        # Convert to RGB if necessary (for JPEG output)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Resize if too large
        if img.size[0] > MAX_IMAGE_SIZE[0] or img.size[1] > MAX_IMAGE_SIZE[1]:
            img.thumbnail(MAX_IMAGE_SIZE, Image.Resampling.LANCZOS)
            logger.debug(f"Resized image to {img.size}")

        # Convert to JPEG for consistency
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=85, optimize=True)
        optimized = output.getvalue()

        logger.debug(
            f"Optimized image: {len(image_data)} -> {len(optimized)} bytes"
        )

        return optimized, "image/jpeg"

    except Exception as e:
        logger.warning(f"Could not optimize image: {e}, using original")
        return image_data, mime_type


async def process_receipt_image(
    image_data: bytes,
    llm: LLMProvider,
    mime_type: str = "image/jpeg",
) -> ParsedReceipt | None:
    """Process a receipt image and extract expense information.

    Args:
        image_data: Raw image bytes
        llm: LLM provider instance
        mime_type: Image MIME type

    Returns:
        ParsedReceipt with extracted expenses, or None if parsing failed
    """
    # Validate image size
    if len(image_data) > MAX_IMAGE_BYTES:
        logger.warning(f"Image too large: {len(image_data)} bytes")
        # Try to optimize it
        image_data, mime_type = optimize_image(image_data, mime_type)

        if len(image_data) > MAX_IMAGE_BYTES:
            logger.error("Image still too large after optimization")
            return None

    # Optimize image for better results
    image_data, mime_type = optimize_image(image_data, mime_type)

    # Parse the receipt
    return await parse_receipt_image(image_data, llm, mime_type)


async def extract_text_from_image(
    image_data: bytes,
    llm: LLMProvider,
    mime_type: str = "image/jpeg",
) -> str | None:
    """Extract general text content from an image using vision LLM.

    Useful for screenshots or text-heavy images that aren't receipts.
    """
    prompt = """Extract all text visible in this image.
If the image contains expense-related information (amounts, prices, purchases),
format it as a clear statement like "Spent $X on Y".

Return ONLY the extracted text, no explanations."""

    try:
        image_data, mime_type = optimize_image(image_data, mime_type)

        text = await llm.complete_with_image(
            prompt=prompt,
            image_data=image_data,
            image_type=mime_type,
            temperature=0.1,
            max_tokens=500,
        )

        return text.strip() if text else None

    except Exception as e:
        logger.error(f"Error extracting text from image: {e}")
        return None


async def process_document_image(
    image_data: bytes,
    llm: LLMProvider,
    mime_type: str = "image/jpeg",
) -> ParsedReceipt | None:
    """Process a document/screenshot that might contain expense info.

    This is more flexible than receipt parsing - handles bank statements,
    screenshots of purchases, etc.
    """
    prompt = """Analyze this image for any expense or purchase information.

Look for:
- Transaction amounts and descriptions
- Purchase receipts or invoices
- Bank/credit card statements
- Payment confirmations
- Shopping cart screenshots

Return a JSON object with:
- expenses: array of {amount, currency, description, category, date}
- store_name: merchant/store name if visible
- total: total amount if this is a receipt/invoice
- date: transaction date in YYYY-MM-DD format

Categories: Food & Dining, Transportation, Shopping, Entertainment, Bills & Utilities, Health, Travel, Education, Groceries, Other

If no expense information is found, return: {"error": "No expense information found"}

Return ONLY the JSON object."""

    try:
        image_data, mime_type = optimize_image(image_data, mime_type)

        response = await llm.complete_with_image(
            prompt=prompt,
            image_data=image_data,
            image_type=mime_type,
            temperature=0.1,
            max_tokens=1000,
        )

        import json
        from datetime import date, datetime
        from decimal import Decimal

        from src.llm.expense_parser import ParsedExpense

        # Clean up response
        response = response.strip()
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        response = response.strip()

        data = json.loads(response)

        if "error" in data:
            return None

        # Parse date
        doc_date = date.today()
        if data.get("date"):
            try:
                doc_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
            except ValueError:
                pass

        # Parse expenses
        expenses = []
        for exp in data.get("expenses", []):
            expenses.append(
                ParsedExpense(
                    amount=Decimal(str(exp.get("amount", 0))),
                    currency=exp.get("currency", "USD").upper(),
                    description=exp.get("description", ""),
                    category=exp.get("category"),
                    expense_date=doc_date,
                    raw_input="[Document image]",
                )
            )

        if not expenses:
            return None

        return ParsedReceipt(
            expenses=expenses,
            store_name=data.get("store_name"),
            total=Decimal(str(data["total"])) if data.get("total") else None,
        )

    except Exception as e:
        logger.error(f"Error processing document image: {e}")
        return None
