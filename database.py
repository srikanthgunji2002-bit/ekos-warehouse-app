import os
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, DateTime, Boolean, JSON
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./warehouse.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(String, default="employee")

class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    phone = Column(String)
    gstin = Column(String, nullable=True)
    email = Column(String)
    address = Column(String)

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String, unique=True, index=True)
    name = Column(String)
    hsn_code = Column(String, default="8302")
    stock_qty = Column(Integer, default=0)
    reorder_level = Column(Integer, default=10)

class StockUpdateLog(Base):
    __tablename__ = "stock_update_logs"
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    updated_by = Column(String)
    change_type = Column(String)
    qty_changed = Column(Integer)
    new_total_qty = Column(Integer)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    product = relationship("Product")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String, unique=True, index=True)
    customer_name = Column(String)
    customer_phone = Column(String, nullable=True)
    product_details = Column(String)
    quantity = Column(Integer)
    order_date = Column(String)
    expected_delivery_date = Column(String)
    status = Column(String, default="upcoming")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    total_amount = Column(Float)
    tax_amount = Column(Float, default=0.0)
    paid_amount = Column(Float, default=0.0)
    include_gst = Column(Boolean, default=True)
    status = Column(String, default="unpaid")
    currency = Column(String, default="INR")
    order_date = Column(String, nullable=True)
    delivery_date = Column(String, nullable=True)
    custom_sections = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    customer = relationship("Customer")
    items = relationship("Transaction", back_populates="invoice", cascade="all, delete-orphan")

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    change_type = Column(String)
    quantity = Column(Integer)
    unit_price = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    product = relationship("Product")
    invoice = relationship("Invoice", back_populates="items")

Base.metadata.create_all(bind=engine)
