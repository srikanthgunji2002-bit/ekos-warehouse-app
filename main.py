import os, datetime, io, hashlib
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Dict, Optional
import database as db
import openpyxl

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

app = FastAPI(title="EKOS STOCK MANAGEMENT")

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def get_db():
    session = db.SessionLocal()
    try:
        yield session
    finally:
        session.close()

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

# Pydantic Schemas
class LoginRequest(BaseModel):
    username: str
    password: str

class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "employee"

class AdminCredsUpdate(BaseModel):
    current_username: str
    current_password: str
    new_username: str
    new_password: str

class ProductCreate(BaseModel):
    sku: str
    name: str
    hsn_code: str = "8302"
    stock_qty: int
    reorder_level: int = 5
    updated_by: str = "Admin"

class ProductStockAdd(BaseModel):
    sku: str
    name: str
    hsn_code: str
    add_qty: int
    updated_by: str = "System"

class OrderCreate(BaseModel):
    order_number: str
    customer_name: str
    customer_phone: Optional[str] = ""  # Added Phone Field
    product_details: str
    quantity: int
    order_date: str
    expected_delivery_date: str
    status: str = "upcoming"

class OrderUpdateStatus(BaseModel):
    status: str

class CustomerCreate(BaseModel):
    name: str
    phone: str
    gstin: str = ""
    email: str
    address: str

class InvoiceCreate(BaseModel):
    customer_id: int
    product_id: int
    quantity: int
    unit_price: float
    include_gst: bool = True
    tax_rate: float = 18.0
    paid_amount: float
    currency: str = "INR"
    order_date: str = ""
    delivery_date: str = ""
    custom_sections: Optional[Dict[str, str]] = {}

# Auth & User Routes
@app.get("/login", response_class=HTMLResponse)
def page_login(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")

@app.post("/api/login")
def login(req: LoginRequest, s: Session = Depends(get_db)):
    if s.query(db.User).count() == 0:
        s.add(db.User(username="admin", password_hash=hash_password("adminpassword"), role="admin"))
        s.add(db.User(username="employee", password_hash=hash_password("employeepassword"), role="employee"))
        s.commit()
        
    hashed = hash_password(req.password)
    user = s.query(db.User).filter(db.User.username == req.username, db.User.password_hash == hashed).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    return {"role": user.role, "username": user.username}

@app.get("/api/users")
def get_users(s: Session = Depends(get_db)):
    users = s.query(db.User).all()
    return [{"id": u.id, "username": u.username, "role": u.role} for u in users]

@app.post("/api/users")
def create_user(u: UserCreate, s: Session = Depends(get_db)):
    existing = s.query(db.User).filter(db.User.username == u.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    new_u = db.User(username=u.username, password_hash=hash_password(u.password), role=u.role)
    s.add(new_u)
    s.commit()
    return {"message": f"User {u.username} created successfully"}

@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, s: Session = Depends(get_db)):
    user = s.query(db.User).filter(db.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.username == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete root admin account")
    s.delete(user)
    s.commit()
    return {"message": "User removed"}

@app.put("/api/admin/credentials")
def update_admin_credentials(req: AdminCredsUpdate, s: Session = Depends(get_db)):
    user = s.query(db.User).filter(db.User.username == req.current_username, db.User.role == "admin").first()
    if not user:
        raise HTTPException(status_code=404, detail="Admin account not found")
    
    if user.password_hash != hash_password(req.current_password):
        raise HTTPException(status_code=400, detail="Security Verification Failed: Current Password is incorrect!")

    user.username = req.new_username
    user.password_hash = hash_password(req.new_password)
    s.commit()
    return {"message": "Admin credentials verified & updated successfully."}

# HTML Page Routes
@app.get("/", response_class=HTMLResponse)
def page_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html")

@app.get("/inventory", response_class=HTMLResponse)
def page_inventory(request: Request):
    return templates.TemplateResponse(request=request, name="inventory.html")

@app.get("/orders", response_class=HTMLResponse)
def page_orders(request: Request):
    return templates.TemplateResponse(request=request, name="orders.html")

@app.get("/sales", response_class=HTMLResponse)
def page_sales(request: Request):
    return templates.TemplateResponse(request=request, name="sales.html")

@app.get("/invoices", response_class=HTMLResponse)
def page_invoices(request: Request):
    return templates.TemplateResponse(request=request, name="invoices.html")

@app.get("/settings", response_class=HTMLResponse)
def page_settings(request: Request):
    return templates.TemplateResponse(request=request, name="settings.html")

# Products API
@app.get("/api/products")
def get_products(s: Session = Depends(get_db)):
    return s.query(db.Product).all()

@app.post("/api/products")
def create_product(prod: ProductCreate, s: Session = Depends(get_db)):
    db_prod = db.Product(sku=prod.sku, name=prod.name, hsn_code=prod.hsn_code, stock_qty=prod.stock_qty, reorder_level=prod.reorder_level)
    s.add(db_prod)
    s.commit()
    s.refresh(db_prod)

    log = db.StockUpdateLog(product_id=db_prod.id, updated_by=prod.updated_by, change_type="IN", qty_changed=prod.stock_qty, new_total_qty=prod.stock_qty)
    s.add(log)
    s.commit()
    return db_prod

@app.put("/api/products/{product_id}")
def edit_product_cumulative(product_id: int, payload: ProductStockAdd, s: Session = Depends(get_db)):
    prod = s.query(db.Product).filter(db.Product.id == product_id).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    
    prod.stock_qty += payload.add_qty
    prod.sku = payload.sku
    prod.name = payload.name
    prod.hsn_code = payload.hsn_code
    s.commit()

    log = db.StockUpdateLog(product_id=prod.id, updated_by=payload.updated_by, change_type="IN" if payload.add_qty >= 0 else "OUT", qty_changed=payload.add_qty, new_total_qty=prod.stock_qty)
    s.add(log)
    s.commit()
    return {"message": f"Added {payload.add_qty} to stock. New Total: {prod.stock_qty}"}

@app.delete("/api/products/{product_id}")
def delete_product(product_id: int, s: Session = Depends(get_db)):
    prod = s.query(db.Product).filter(db.Product.id == product_id).first()
    if prod:
        s.delete(prod)
        s.commit()
    return {"message": "Product deleted"}

@app.get("/api/products/update-logs")
def get_stock_update_logs(s: Session = Depends(get_db)):
    logs = s.query(db.StockUpdateLog).order_by(db.StockUpdateLog.created_at.desc()).all()
    out = []
    for l in logs:
        out.append({
            "id": l.id,
            "product_id": l.product_id,
            "product_name": l.product.name if l.product else "Deleted Item",
            "sku": l.product.sku if l.product else "-",
            "updated_by": l.updated_by,
            "change_type": l.change_type,
            "qty_changed": l.qty_changed,
            "new_total_qty": l.new_total_qty,
            "timestamp": l.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            "date": l.created_at.strftime('%Y-%m-%d')
        })
    return out

# Orders API
@app.get("/api/orders")
def get_orders(s: Session = Depends(get_db)):
    return s.query(db.Order).order_by(db.Order.created_at.desc()).all()

@app.post("/api/orders")
def create_order(order: OrderCreate, s: Session = Depends(get_db)):
    db_order = db.Order(**order.dict())
    s.add(db_order)
    s.commit()
    s.refresh(db_order)
    return db_order

@app.put("/api/orders/{order_id}/status")
def update_order_status(order_id: int, payload: OrderUpdateStatus, s: Session = Depends(get_db)):
    ord_obj = s.query(db.Order).filter(db.Order.id == order_id).first()
    if not ord_obj:
        raise HTTPException(status_code=404, detail="Order not found")
    ord_obj.status = payload.status
    s.commit()
    return {"message": f"Order status updated to {payload.status}"}

@app.delete("/api/orders/{order_id}")
def delete_order(order_id: int, s: Session = Depends(get_db)):
    ord_obj = s.query(db.Order).filter(db.Order.id == order_id).first()
    if ord_obj:
        s.delete(ord_obj)
        s.commit()
    return {"message": "Order deleted"}

# Customers API
@app.post("/api/customers")
def create_customer(cust: CustomerCreate, s: Session = Depends(get_db)):
    db_cust = db.Customer(**cust.dict())
    s.add(db_cust)
    s.commit()
    return db_cust

@app.get("/api/customers")
def get_customers(s: Session = Depends(get_db)):
    return s.query(db.Customer).all()

# Invoices API
@app.get("/api/invoices")
def get_invoices_history(s: Session = Depends(get_db)):
    invoices = s.query(db.Invoice).order_by(db.Invoice.created_at.desc()).all()
    results = []
    for inv in invoices:
        results.append({
            "id": inv.id,
            "customer_name": inv.customer.name if inv.customer else "N/A",
            "total_amount": inv.total_amount,
            "paid_amount": inv.paid_amount,
            "currency": inv.currency,
            "status": inv.status,
            "order_date": inv.order_date or inv.created_at.strftime('%Y-%m-%d'),
            "delivery_date": inv.delivery_date or 'N/A'
        })
    return results

@app.post("/api/invoices")
def create_invoice(inv: InvoiceCreate, s: Session = Depends(get_db)):
    prod = s.query(db.Product).filter(db.Product.id == inv.product_id).first()
    cust = s.query(db.Customer).filter(db.Customer.id == inv.customer_id).first()
    
    if not prod or prod.stock_qty < inv.quantity:
        raise HTTPException(status_code=400, detail="Insufficient stock available")

    prod.stock_qty -= inv.quantity
    
    subtotal = inv.unit_price * inv.quantity
    tax_amt = subtotal * (inv.tax_rate / 100.0) if inv.include_gst else 0.0
    total = subtotal + tax_amt
    
    new_inv = db.Invoice(
        customer_id=cust.id, 
        total_amount=total, 
        tax_amount=tax_amt, 
        paid_amount=inv.paid_amount, 
        include_gst=inv.include_gst,
        status="paid" if inv.paid_amount >= total else "unpaid",
        currency=inv.currency,
        order_date=inv.order_date,
        delivery_date=inv.delivery_date,
        custom_sections=inv.custom_sections
    )
    s.add(new_inv)
    s.commit()
    s.refresh(new_inv)

    txn = db.Transaction(product_id=prod.id, invoice_id=new_inv.id, change_type="OUT", quantity=inv.quantity, unit_price=inv.unit_price)
    s.add(txn)
    
    log = db.StockUpdateLog(product_id=prod.id, updated_by="Invoice Sale", change_type="OUT", qty_changed=-inv.quantity, new_total_qty=prod.stock_qty)
    s.add(log)
    s.commit()

    return {"message": "Invoice Created", "invoice_id": new_inv.id}

# Analytics
@app.get("/api/analytics")
def get_analytics(s: Session = Depends(get_db)):
    total_revenue = s.query(func.sum(db.Invoice.total_amount)).scalar() or 0.0
    total_received = s.query(func.sum(db.Invoice.paid_amount)).scalar() or 0.0
    pending_bills = total_revenue - total_received
    low_stock_count = s.query(db.Product).filter(db.Product.stock_qty <= db.Product.reorder_level).count()
    total_products = s.query(db.Product).count()

    return {
        "total_revenue": total_revenue,
        "total_received": total_received,
        "pending_bills": pending_bills,
        "low_stock_count": low_stock_count,
        "total_products": total_products
    }

@app.get("/api/analytics/daily-stock")
def get_daily_stock(s: Session = Depends(get_db)):
    today_str = datetime.datetime.utcnow().strftime('%Y-%m-%d')
    prods = s.query(db.Product).all()
    logs = []
    
    for p in prods:
        out_today = s.query(func.sum(db.Transaction.quantity)).filter(
            db.Transaction.product_id == p.id,
            db.Transaction.change_type == "OUT",
            func.date(db.Transaction.created_at) == today_str
        ).scalar() or 0
        
        logs.append({
            "product_name": p.name,
            "sku": p.sku,
            "current_stock": p.stock_qty,
            "out_today": out_today
        })
    return logs

# Excel Exports
@app.get("/api/export/products")
def export_products_excel(s: Session = Depends(get_db)):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stock Inventory"
    ws.append(["ID", "SKU Code", "Product Name", "HSN/SAC Code", "Current Stock Qty", "Reorder Level"])

    for p in s.query(db.Product).all():
        ws.append([p.id, p.sku, p.name, p.hsn_code, p.stock_qty, p.reorder_level])

    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    return StreamingResponse(
        stream, 
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ekos_stock_inventory.xlsx"}
    )

@app.get("/api/export/invoices")
def export_invoices_excel(s: Session = Depends(get_db)):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales Invoices"
    ws.append(["Invoice ID", "Customer Name", "Order Date", "Delivery Date", "Currency", "Total Amount", "Paid Amount", "Payment Status"])

    for inv in s.query(db.Invoice).all():
        ws.append([
            f"EKOS-{inv.id:04d}",
            inv.customer.name if inv.customer else 'N/A',
            inv.order_date or '',
            inv.delivery_date or '',
            inv.currency,
            inv.total_amount,
            inv.paid_amount,
            inv.status.upper()
        ])

    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    return StreamingResponse(
        stream, 
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ekos_sales_invoices.xlsx"}
    )

# PDF Generation
@app.get("/api/invoices/{invoice_id}/pdf")
def generate_pdf_invoice(invoice_id: int, s: Session = Depends(get_db)):
    inv = s.query(db.Invoice).filter(db.Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    txn = s.query(db.Transaction).filter(db.Transaction.invoice_id == inv.id).first()
    prod = txn.product if txn else None
    sym = "Rs. " if inv.currency == "INR" else "$ "

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.rect(30, 30, 550, 730)

    # Header
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, 740, "EKOS")
    c.setFont("Helvetica", 9)
    c.drawString(40, 725, "Kammuguda, Turkayamjal, Hyderabad, Telangana")
    c.drawString(40, 712, "Ph No: 9704242247  | Web: www.ekosindia.com")

    logo_path = "static/logo.png"
    if os.path.exists(logo_path):
        c.drawImage(logo_path, 430, 685, width=160, height=75, preserveAspectRatio=True)

    c.line(30, 695, 580, 695)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(240, 680, "TAX INVOICE")
    c.line(30, 672, 580, 672)

    # Details
    c.line(280, 570, 280, 672)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(40, 660, "Customer Details:")
    c.setFont("Helvetica", 8)
    c.drawString(40, 645, f"M/S: {inv.customer.name}")
    c.drawString(40, 632, f"Address: {inv.customer.address}")
    c.drawString(40, 619, f"Phone: {inv.customer.phone}")
    
    if inv.include_gst and inv.customer.gstin:
        c.drawString(40, 606, f"GSTIN: {inv.customer.gstin}")

    c.drawString(290, 660, f"Invoice No.: EKOS-{inv.id:04d}")
    c.drawString(290, 645, f"Order Date: {inv.order_date or inv.created_at.strftime('%Y-%m-%d')}")
    c.drawString(290, 630, f"Delivery Date: {inv.delivery_date or 'N/A'}")

    y_custom = 615
    if inv.custom_sections:
        for k, v in inv.custom_sections.items():
            c.drawString(290, y_custom, f"{k}: {v}")
            y_custom -= 12

    c.line(30, 570, 580, 570)

    c.setFont("Helvetica-Bold", 8)
    c.drawString(35, 558, "Sr.")
    c.drawString(60, 558, "Name of Product / Service")
    c.drawString(280, 558, "HSN/SAC")
    c.drawString(350, 558, "Qty")
    c.drawString(420, 558, f"Rate ({inv.currency})")
    c.drawString(500, 558, f"Total ({inv.currency})")
    c.line(30, 550, 580, 550)

    if prod and txn:
        subtotal = txn.unit_price * txn.quantity
        c.setFont("Helvetica", 8)
        c.drawString(35, 535, "1")
        c.drawString(60, 535, prod.name)
        c.drawString(280, 535, prod.hsn_code)
        c.drawString(350, 535, f"{txn.quantity} NOS")
        c.drawString(420, 535, f"{sym}{prod.unit_price:.2f}")
        c.drawString(500, 535, f"{sym}{subtotal:.2f}")

    c.line(30, 250, 580, 250)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(350, 235, "Total Taxable:")
    c.drawString(500, 235, f"{sym}{(inv.total_amount - inv.tax_amount):.2f}")
    if inv.include_gst:
        c.drawString(350, 220, "IGST (18%):")
        c.drawString(500, 220, f"{sym}{inv.tax_amount:.2f}")
    c.drawString(350, 205, "Grand Total:")
    c.drawString(500, 205, f"{sym}{inv.total_amount:.2f}")

    c.line(30, 180, 580, 180)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(40, 165, "Bank Details")
    c.setFont("Helvetica", 8)
    c.drawString(40, 150, "Bank: SBI Bank")
    c.drawString(40, 137, "Acc No: 43666829758")
    c.drawString(40, 124, "IFSC: SBIN0021984")

    c.drawString(380, 60, "For EKOS SUSTAINABLE PACKAGING")
    c.drawString(410, 40, "Authorised Signatory")

    c.showPage()
    c.save()

    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": f"inline; filename=invoice_{invoice_id}.pdf"})