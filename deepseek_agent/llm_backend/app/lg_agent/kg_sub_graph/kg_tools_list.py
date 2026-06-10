from typing import Literal, Optional

from pydantic import BaseModel
from pydantic import Field


class cypher_query(BaseModel):
    """如果用户问的是关于产品价格、库存、规格等，则使用这个工具，生成Cypher查询语句进行查询"""

    task: str = Field(..., description="The task the Cypher query must answer.")

class predefined_cypher(BaseModel):
    """这个工具包含预定义的Cypher查询语句，用于快速响应各种电商场景的查询需求。
    
    根据用户问题的类型，可以选择以下类别的查询：
    
    1. 产品类查询：
       - product_by_name: 通过产品名称查询产品信息
       - product_by_category: 通过类别名称查询该类别下的所有产品
       - product_by_supplier: 查询特定供应商提供的所有产品
       - products_low_stock: 查询库存不足的产品
       - products_popular: 查询最受欢迎(评论最多)的产品
    
    2. 客户类查询：
       - customer_by_name: 通过名称查询客户信息
       - customer_orders: 查询特定客户的所有订单
       - customer_purchase_history: 查询特定客户的购买历史
    
    3. 订单类查询：
       - order_by_id: 通过订单ID查询订单信息
       - order_details: 查询特定订单的详细信息(包含的产品)
       - recent_orders: 查询最近的订单
       - delayed_orders: 查询延迟发货的订单
    
    4. 供应商类查询：
       - supplier_by_country: 查询特定国家的供应商
       - supplier_products: 查询特定供应商提供的所有产品
    
    5. 类别类查询：
       - all_categories: 查询所有产品类别
       - category_products: 查询特定类别下的所有产品
       - category_product_count: 查询每个类别包含的产品数量
    
    6. 员工类查询：
       - employee_by_name: 通过姓名查询员工信息
       - employee_processed_orders: 查询特定员工处理的所有订单
    
    7. 评论类查询：
       - product_reviews: 查询特定产品的所有评论
       - top_rated_products: 查询评分最高的产品
    
    8. 销售分析类查询：
       - product_sales: 查询特定产品的总销售额
       - category_sales: 查询各类别的总销售额
       - monthly_sales: 查询每月的销售情况
    
    9. 智能家居相关查询：
       - smart_home_products: 查询所有智能家居产品
       - smart_speakers: 查询智能音箱类产品
       - smart_lighting: 查询智能照明类产品

    10. 单商铺电商客服知识查询：
       - shop_profile: 查询店铺地址、营业时间、评分等基础信息
       - shop_open_hours: 查询店铺营业时间
       - voucher_list: 查询店铺当前同步到知识库的优惠券
       - voucher_rule: 查询指定优惠券的使用规则
       - activity_list: 查询店铺活动
       - after_sale_policy: 查询售后政策
    
    请根据用户的问题选择最合适的查询，并根据需要替换查询中的参数值（如$product_name, $category_name等）。
    """

    query: str = Field(..., description="query the graph must include the question")
    parameters: dict = Field(..., description="parameters for the query to Neo4j")

class microsoft_graphrag_query(BaseModel):
    """如果用户问的问题是关于产品的故障、售后、保修、维修、退换货以及评价等，则使用这个工具"""
    query: str = Field(..., description="query the graph must include the question")


class commerce_live_query(BaseModel):
    """如果用户问的是订单状态、秒杀实时库存、是否还能购买、是否已经买过某张券等实时业务状态，则使用这个工具调用业务后端"""

    action: Literal["order_status", "user_orders", "seckill_status", "purchase_eligibility"] = Field(
        ...,
        description="实时业务动作：order_status、user_orders、seckill_status、purchase_eligibility",
    )
    query: str = Field(..., description="用户原始问题")
    order_id: Optional[int] = Field(None, description="订单ID，查询订单状态时必填")
    user_id: Optional[int] = Field(None, description="用户ID，查询用户订单或购买资格时必填")
    voucher_id: Optional[int] = Field(None, description="优惠券ID，查询秒杀状态或购买资格时必填")
    

class real_time_network_query(BaseModel):
    """如果用户问的问题是关于一些实时的产品有效信息需要联网检索的话，则使用这个工具"""
    query: str = Field(..., description="query the network must include the question")


