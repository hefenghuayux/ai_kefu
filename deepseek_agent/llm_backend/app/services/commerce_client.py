from typing import Any, Dict, Optional

import aiohttp

from app.core.config import settings


class CommerceApiClient:
    """调用单商铺电商平台的内部客服接口，只处理实时业务状态。"""

    def __init__(self, base_url: Optional[str] = None, internal_token: Optional[str] = None):
        self.base_url = (base_url or settings.COMMERCE_API_BASE_URL).rstrip("/")
        self.internal_token = internal_token or settings.COMMERCE_INTERNAL_TOKEN

    async def live_query(
        self,
        *,
        action: str,
        order_id: Optional[int] = None,
        user_id: Optional[int] = None,
        voucher_id: Optional[int] = None,
        product_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        endpoint = self._endpoint(
            action=action,
            order_id=order_id,
            user_id=user_id,
            voucher_id=voucher_id,
            product_id=product_id,
        )
        headers = {"X-Internal-Token": self.internal_token}
        timeout = aiohttp.ClientTimeout(total=settings.COMMERCE_API_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{self.base_url}{endpoint}", headers=headers) as response:
                payload = await response.json(content_type=None)
                if response.status >= 400:
                    raise RuntimeError(
                        f"Commerce API failed: status={response.status}, payload={payload}"
                    )
                return payload

    def _endpoint(
        self,
        *,
        action: str,
        order_id: Optional[int],
        user_id: Optional[int],
        voucher_id: Optional[int],
        product_id: Optional[int],
    ) -> str:
        if action == "order_status":
            if order_id is None:
                raise ValueError("order_status 需要 order_id")
            return f"/internal/customer-service/orders/{order_id}"
        if action == "user_orders":
            if user_id is None:
                raise ValueError("user_orders 需要 user_id")
            return f"/internal/customer-service/users/{user_id}/orders"
        if action == "seckill_status":
            if voucher_id is None:
                raise ValueError("seckill_status 需要 voucher_id")
            return f"/internal/customer-service/vouchers/{voucher_id}/seckill-status"
        if action == "purchase_eligibility":
            if user_id is None or voucher_id is None:
                raise ValueError("purchase_eligibility 需要 user_id 和 voucher_id")
            return f"/internal/customer-service/users/{user_id}/vouchers/{voucher_id}/eligibility"
        if action == "product_detail":
            if product_id is None:
                raise ValueError("product_detail 需要 product_id")
            return f"/internal/customer-service/products/{product_id}"
        if action == "product_stock":
            if product_id is None:
                raise ValueError("product_stock 需要 product_id")
            return f"/internal/customer-service/products/{product_id}/stock"
        if action == "user_product_orders":
            if user_id is None:
                raise ValueError("user_product_orders 需要 user_id")
            return f"/internal/customer-service/users/{user_id}/product-orders"
        raise ValueError(f"不支持的 commerce live query action: {action}")
