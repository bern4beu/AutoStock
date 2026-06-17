# AutoStock 🔧

Sistema web de gestión de ventas, stock e inventario diseñado específicamente para repuestos de automóviles.

---

## ¿Qué es AutoStock?

AutoStock es una aplicación web desarrollada en Python con Flask que permite a las repuesteras gestionar su operación diaria desde un solo lugar: ventas, stock, clientes, proveedores, cuentas corrientes y reportes.

El sistema es **multi-tenant**: cada negocio opera en un entorno aislado con sus propios datos, usuarios y configuraciones.

---

## Funcionalidades

### 📦 Gestión de productos e inventario
- Alta de productos con variantes (medidas, dimensiones)
- Asociación de productos a vehículos (marca, modelo, motor)
- Control de stock con alertas de stock bajo
- Historial de movimientos de stock
- Marcar pedidos pendientes y registrar recepción de mercadería
- Productos más vendidos y más rentables

### 🛒 Ventas
- Registro de ventas con múltiples productos
- Soporte para ventas al contado y en cuenta corriente
- Anulación de ventas con devolución automática de stock
- Historial de ventas con filtros por fecha

### 👥 Clientes y proveedores
- ABM de clientes y proveedores
- Gestión de cuentas corrientes con historial de movimientos y pagos

### 💰 Caja
- Registro de ingresos por venta y por taller
- Desglose por método de pago (efectivo, transferencia, débito, crédito)
- Filtros por período

### 📊 Reportes
- Ventas del período con totales por método de pago
- Productos más vendidos y más rentables
- Stock bajo en PDF
- Movimientos de stock

### 👤 Usuarios
- Sistema de roles: administrador y empleado
- Alta, baja y activación/desactivación de usuarios
- Cambio de contraseña

---

## Stack tecnológico

| Capa | Tecnología |
|------|-----------|
| Backend | Python 3 · Flask |
| Base de datos | PostgreSQL (via Supabase) |
| Autenticación | Flask-Login · bcrypt |
| Frontend | Jinja2 · CSS · JavaScript vanilla |
| Deploy | Gunicorn · Render (o compatible con Procfile) |

---

## Estructura del proyecto

```
autostock/
├── app.py                  # Aplicación principal: rutas, lógica de negocio
├── requirements.txt        # Dependencias Python
├── Procfile                # Configuración de deploy (Gunicorn)
├── static/
│   ├── css/
│   │   ├── corporate.css   # Estilos principales
│   │   └── print.css       # Estilos para impresión
│   └── js/
│       ├── productos.js
│       ├── venta.js
│       └── ...
└── templates/              # Vistas HTML (Jinja2)
    ├── base_layout.html
    ├── home.html
    ├── productos.html
    ├── venta.html
    └── ...
```

---

## Instalación local

### Requisitos previos
- Python 3.10+
- PostgreSQL (o una instancia en Supabase)

### Pasos

```bash
# 1. Clonar el repositorio
git clone https://github.com/bern4beu/AutoStock.git
cd autostock

# 2. Crear y activar un entorno virtual
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Editar .env con tus credenciales

# 5. Iniciar la aplicación
python app.py
```

### Variables de entorno requeridas

Crear un archivo `.env` en la raíz del proyecto con las siguientes variables:

```env
SECRET_KEY=una-clave-secreta-segura
DATABASE_URL=postgresql://usuario:contraseña@host:5432/nombre_db
SUPABASE_URL=https://tu-proyecto.supabase.co
SUPABASE_KEY=tu-clave-supabase
```

---

## Deploy

El proyecto incluye un `Procfile` para deploy en plataformas compatibles como Render o Railway:

```
web: gunicorn app:app --workers 1 --timeout 120 --keep-alive 5
```

---

## Autor

Desarrollado por **Azul Ackerl**  
📧 azulackerl912@gmail.com  
🔗 www.linkedin.com/in/azul-ackerl-a7aa70296

---

## Estado del proyecto

Actualmente en producción con un cliente real. El sistema está en desarrollo activo con nuevas funcionalidades en camino.
