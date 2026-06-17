from flask import Flask, request, render_template, jsonify, redirect, url_for, session, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from urllib.parse import quote
import psycopg2
import bcrypt
import os
from dotenv import load_dotenv
from supabase import create_client
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


app = Flask(__name__)


limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[]
)




from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).parent / '.env', override=True)

import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024 # 5MB máx

@app.errorhandler(404)
def pagina_no_encontrada(e):
    return render_template('404.html', 
                           mensaje='La página que buscás no existe.'), 404

@app.errorhandler(500)
def error_interno(e):
    return render_template('404.html',
                           mensaje='Ocurrió un error interno. Intentá de nuevo en unos minutos.'), 500

# Clave secreta para sesiones (necesaria para Flask-Login)
secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    raise RuntimeError(
        "SECRET_KEY no configurada. "
        "Agregá SECRET_KEY=<clave-segura> a tu archivo .env antes de iniciar la app."
    )
app.secret_key = secret_key

# Configurar Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # Redirigir al login si no está autenticado
login_manager.login_message = 'Iniciá sesión para acceder al sistema'

# ============ CLASE USUARIO ============

class Usuario(UserMixin):
    """
    Clase que representa un usuario logueado.
    UserMixin agrega métodos necesarios para Flask-Login:
    - is_authenticated
    - is_active
    - get_id()
    """
    def __init__(self, id, nombre, email, rol, activo, id_negocio):
        self.id = id
        self.nombre = nombre
        self.email = email
        self.rol = rol
        self.activo = activo
        self.id_negocio = id_negocio
    
    def es_admin(self):
        return self.rol == 'admin'


@login_manager.user_loader
def cargar_usuario(user_id):
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT id, nombre, email, rol, activo, id_negocio 
            FROM usuario 
            WHERE id = %s AND activo = TRUE
        """, (user_id,))
        u = cur.fetchone()
    if u:
        return Usuario(u[0], u[1], u[2], u[3], u[4], u[5])
    return None


# ----------------------------------------------

def get_supabase_client():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)

def get_db_connection():
    database_url = os.environ.get("DATABASE_URL")
    return psycopg2.connect(database_url, sslmode="require")

from contextlib import contextmanager

@contextmanager
def get_db():
    """
    Context manager para conexiones a PostgreSQL.
    Garantiza que la conexión siempre se cierra,
    incluso si ocurre una excepción.
    
    Uso:
        with get_db() as (conn, cur):
            cur.execute(...)
            conn.commit()
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        yield conn, cur
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

def formatear_producto_con_dimensiones(producto_tuple):
    """
    Recibe una tupla (id, nombre, alto, ancho, largo, diametro)
    y devuelve (id, nombre_formateado)
    """
    id_prod = producto_tuple[0]
    nombre = producto_tuple[1]
    alto = producto_tuple[2]
    ancho = producto_tuple[3]
    largo = producto_tuple[4]
    diametro = producto_tuple[5]
    
    if alto or ancho or largo or diametro:
        display = f"{nombre} ({alto or ''}x{ancho or ''}x{largo or ''}x{diametro or ''})"
    else:
        display = nombre
    
    return (id_prod, display)

def normalizar_texto(texto):
    """
    Normaliza un texto: capitaliza primera letra de cada palabra, 
    quita espacios extras, y convierte a title case.
    """
    if not texto:
        return texto
    
    texto = texto.strip()
    
    import re
    texto = re.sub(r'\s+', ' ', texto)
    
    texto = texto.title()
    
    return texto

def get_features(id_negocio):
    """
    Devuelve un set con las features habilitadas para un negocio.
    Uso en templates: {% if 'pdf_stock_bajo' in features %}
    """
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT feature FROM negocio_features WHERE id_negocio = %s
        """, (id_negocio,))
        return {row[0] for row in cur.fetchall()}

@app.context_processor
def inject_features():
    """
    Inyecta las features del negocio actual en todos los templates
    automáticamente, sin necesidad de pasarlas manualmente en cada ruta.
    """
    try:
        if current_user.is_authenticated:
            features = get_features(current_user.id_negocio)
        else:
            features = set()
    except Exception:
        features = set()
    return dict(features=features)

def encontrar_similitud(texto, lista_existentes):
    """
    Busca si hay algún texto similar en la lista.
    Solo retorna coincidencia si es EXACTA (ignorando mayúsculas/minúsculas).
    Retorna el texto similar si existe, o None.
    """
    if not texto or not lista_existentes:
        return None
    
    texto_lower = texto.lower().strip()
    
    for existente in lista_existentes:
        existente_lower = existente.lower().strip()
        
        # Solo coincidencia EXACTA (ignorando mayúsculas)
        if texto_lower == existente_lower:
            return existente
    
    return None

def registrar_movimiento_stock(cur, id_producto, tipo, cantidad, stock_antes, stock_despues, motivo=None, id_usuario=None, precio_compra=None, precio_venta=None):
    """
    Registra un movimiento de stock en la base de datos.
    
    Args:
        cur: cursor de la conexión
        id_producto: ID del producto_variante
        tipo: 'venta', 'pedido_recibido', 'ajuste_positivo', 'ajuste_negativo'
        cantidad: cantidad del movimiento (siempre positiva)
        stock_antes: stock antes del movimiento
        stock_despues: stock después del movimiento
        motivo: descripción opcional del movimiento
        id_usuario: ID del usuario que hizo el movimiento (current_user.id)
        precio_compra: precio de compra al momento del movimiento
        precio_venta: precio de venta al momento del movimiento
    """
    cur.execute("""
        INSERT INTO movimiento_stock 
        (id_producto_variante, tipo, cantidad, stock_antes, stock_despues, motivo, id_usuario, precio_compra, precio_venta)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (id_producto, tipo, cantidad, stock_antes, stock_despues, motivo, id_usuario, precio_compra, precio_venta))


def es_url_segura(url):
    """
    Verifica que una URL de redirección sea segura:
    debe ser relativa o apuntar al mismo host.
    Previene ataques de Open Redirect.
    """
    if not url:
        return False
    
    from urllib.parse import urlparse, urljoin
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, url))
    
    return (
        test_url.scheme in ('http', 'https') and
        ref_url.netloc == test_url.netloc
    )


def validar_imagen(imagen):
    import filetype

    EXTENSIONES_PERMITIDAS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
    TIPOS_PERMITIDOS = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}

    if '.' not in imagen.filename:
        return False, 'El archivo no tiene extensión.'

    extension = imagen.filename.rsplit('.', 1)[-1].lower()
    if extension not in EXTENSIONES_PERMITIDAS:
        return False, f'Extensión "{extension}" no permitida. Usá JPG, PNG, GIF o WEBP.'

    imagen_bytes = imagen.read()

    if len(imagen_bytes) == 0:
        return False, 'El archivo está vacío.'

    if len(imagen_bytes) > 5 * 1024 * 1024:
        return False, 'La imagen no puede superar los 5MB.'

    tipo = filetype.guess(imagen_bytes)
    if tipo is None or tipo.mime not in TIPOS_PERMITIDOS:
        return False, 'El archivo no es una imagen válida.'

    return True, imagen_bytes


# ---------------------------------

@app.route("/health")
def health():
    return "OK"



# ============ LOGIN / LOGOUT ============

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute") # máx 5 intentos por minuto por IP
def login():
    # Si ya está logueado, redirigir al inicio
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, nombre, email, password_hash, rol, activo, id_negocio
            FROM usuario
            WHERE email = %s
        """, (email,))
        
        u = cur.fetchone()

        logger.debug("Intento de login para: %s", email)

        cur.close()
        conn.close()
        
        if not u:
            return render_template('login.html',
                                 error='Email o contraseña incorrectos')
        
        if not u[5]:  # activo = FALSE
            return render_template('login.html',
                                 error='Tu cuenta está desactivada. Contactá al administrador')
        
        password_hash = u[3].strip() if u[3] else '' 
        
        if not password_hash or password_hash.strip() == '':
            return render_template('login.html',
                                 error='Error en la configuración de tu cuenta. Contactá al administrador')
        
        try:
            password_bytes = password.strip().encode('utf-8')
            hash_bytes = password_hash.strip().encode('utf-8')
            verifica = bcrypt.checkpw(password_bytes, hash_bytes)

            if not verifica:
                logger.debug("Login fallido para: %s", email)
                return render_template('login.html',
                                    error='Email o contraseña incorrectos')
            
        except Exception as e:
            logger.error("Error al verificar contraseña para %s: %s", email, type(e).__name__)
            return render_template('login.html',
                                error='Error al verificar credenciales')
        
        usuario = Usuario(u[0], u[1], u[2], u[4], u[5], u[6])
        login_user(usuario)
        
        next_page = request.args.get('next')
        if not es_url_segura(next_page):
            next_page = url_for('home')
        return redirect(next_page)
    
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))



# ----------- INICIO ---------------------


@app.route('/')
@login_required
def home():
    with get_db() as (conn, cur):

        # Ventas contado del mes
        cur.execute("""
            SELECT COALESCE(SUM(total), 0), COUNT(*)
            FROM venta
            WHERE EXTRACT(MONTH FROM fecha) = EXTRACT(MONTH FROM CURRENT_DATE)
              AND EXTRACT(YEAR FROM fecha) = EXTRACT(YEAR FROM CURRENT_DATE)
              AND id_negocio = %s
              AND tipo_pago = 'contado'
              AND anulada = FALSE
        """, (current_user.id_negocio,))
        r_contado = cur.fetchone()

        # Pagos de cuenta corriente del mes
        cur.execute("""
            SELECT COALESCE(SUM(monto), 0), COUNT(*)
            FROM movimiento_cuenta
            WHERE EXTRACT(MONTH FROM fecha) = EXTRACT(MONTH FROM CURRENT_DATE)
              AND EXTRACT(YEAR FROM fecha) = EXTRACT(YEAR FROM CURRENT_DATE)
              AND id_negocio = %s
              AND tipo = 'pago'
        """, (current_user.id_negocio,))
        r_cc = cur.fetchone()

        # Los demás queries no tienen el bug, no se tocan
        cur.execute("""
            SELECT COUNT(*) FROM producto_variante
            WHERE id_negocio = %s
        """, (current_user.id_negocio,))
        total_productos = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM producto_variante 
            WHERE stock <= stock_minimo 
              AND activo = TRUE
              AND id_negocio = %s
        """, (current_user.id_negocio,))
        stock_bajo = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM cliente
            WHERE id_negocio = %s
        """, (current_user.id_negocio,))
        total_clientes = cur.fetchone()[0]

    stats = {
        "ventas_mes":      f"{float(r_contado[0]) + float(r_cc[0]):.2f}",
        "cantidad_ventas": int(r_contado[1]) + int(r_cc[1]),
        "total_productos": total_productos,
        "stock_bajo":      stock_bajo,
        "total_clientes":  total_clientes,
    }
    return render_template('home.html', stats=stats)


# ----- CAMBIAR PASSWORD --------

@app.route('/cambiar_password', methods=['GET', 'POST'])
@login_required
def cambiar_password():
    if request.method == 'POST':
        password_actual = request.form.get('password_actual', '')
        password_nuevo = request.form.get('password_nuevo', '')
        password_confirmar = request.form.get('password_confirmar', '')

        if password_nuevo != password_confirmar:
            flash('Las contraseñas nuevas no coinciden.', 'error')
            return redirect(url_for('cambiar_password'))

        if len(password_nuevo) < 8:
            flash('La nueva contraseña debe tener al menos 8 caracteres.', 'error')
            return redirect(url_for('cambiar_password'))

        try:
            with get_db() as (conn, cur):
                cur.execute("SELECT password_hash FROM usuario WHERE id = %s", (current_user.id,))
                row = cur.fetchone()

                if not row:
                    flash('Error: Usuario no encontrado.', 'error')
                    return redirect(url_for('cambiar_password'))

                password_hash_actual = row[0]
                password_correcta = False

                if password_hash_actual.startswith('$2b$') or password_hash_actual.startswith('$2a$'):
                    password_correcta = bcrypt.checkpw(
                        password_actual.encode('utf-8'),
                        password_hash_actual.encode('utf-8')
                    )
                elif password_hash_actual.startswith('scrypt:'):
                    flash('Tu usuario fue creado con Supabase Auth. Contactá al administrador.', 'error')
                    return redirect(url_for('cambiar_password'))
                else:
                    flash('Formato de contraseña no soportado. Contactá al administrador.', 'error')
                    return redirect(url_for('cambiar_password'))

                if not password_correcta:
                    flash('La contraseña actual es incorrecta.', 'error')
                    return redirect(url_for('cambiar_password'))

                nuevo_hash = bcrypt.hashpw(password_nuevo.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                cur.execute("""
                    UPDATE usuario SET password_hash = %s WHERE id = %s
                """, (nuevo_hash, current_user.id))
                conn.commit()
                flash('¡Contraseña actualizada correctamente!', 'success')

        except Exception as e:
            flash(f'Error al actualizar la contraseña: {str(e)}', 'error')

        return redirect(url_for('cambiar_password'))

    return render_template('cambiar_password.html')


# ---------- CLIENTES ----------

@app.route('/clientes', methods=['GET', 'POST'])
@login_required
def agregar_cliente():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        contacto = request.form.get('contacto', '').strip()

        if not nombre or len(nombre.strip()) == 0:
            flash('El campo "Nombre" es obligatorio.', 'error')
            return redirect(url_for('agregar_cliente'))

        try:
            with get_db() as (conn, cur):
                cur.execute("""
                    INSERT INTO cliente (nombre, contacto, id_negocio) VALUES (%s, %s, %s)
                """, (nombre, contacto or None, current_user.id_negocio))
                conn.commit()
            flash(f'Cliente "{nombre}" agregado con éxito.', 'success')
        except Exception as e:
            flash(f'Error al guardar cliente: {str(e)}', 'error')

        return redirect(url_for('agregar_cliente'))

    with get_db() as (conn, cur):
        cur.execute("""
            SELECT id, nombre, contacto, TO_CHAR(creado_en, 'DD/MM/YYYY')
            FROM cliente
            WHERE id_negocio = %s
            ORDER BY nombre
        """, (current_user.id_negocio,))
        clientes = [{'id': c[0], 'nombre': c[1], 'contacto': c[2], 'fecha': c[3]}
                    for c in cur.fetchall()]

    return render_template('clientes.html', clientes=clientes)


# ---------- VEHICULOS ----------


@app.route("/agregar_vehiculo", methods=["GET", "POST"])
@login_required
def agregar_vehiculo():
    if request.method == "POST":
        marca_raw = request.form.get("marca", "").strip()
        modelo_raw = request.form.get("modelo", "").strip()
        motor_raw = request.form.get("motor", "").strip()

        if not marca_raw:
            flash('El campo "Marca" es obligatorio.', 'error')
            return redirect(url_for('agregar_vehiculo'))
        if not modelo_raw:
            flash('El campo "Modelo" es obligatorio.', 'error')
            return redirect(url_for('agregar_vehiculo'))
        if not motor_raw:
            flash('El campo "Motor" es obligatorio.', 'error')
            return redirect(url_for('agregar_vehiculo'))

        marca = normalizar_texto(marca_raw)
        modelo = normalizar_texto(modelo_raw)
        motor = normalizar_texto(motor_raw)

        try:
            with get_db() as (conn, cur):
                cur.execute("SELECT DISTINCT marca FROM vehiculo WHERE id_negocio = %s", (current_user.id_negocio,))
                marcas_existentes = [r[0] for r in cur.fetchall()]
                cur.execute("SELECT DISTINCT modelo FROM vehiculo WHERE id_negocio = %s", (current_user.id_negocio,))
                modelos_existentes = [r[0] for r in cur.fetchall()]

                marca_similar = encontrar_similitud(marca, marcas_existentes)
                modelo_similar = encontrar_similitud(modelo, modelos_existentes)
                if marca_similar and marca != marca_similar:
                    marca = marca_similar
                if modelo_similar and modelo != modelo_similar:
                    modelo = modelo_similar

                cur.execute("""
                    INSERT INTO vehiculo (marca, modelo, motor, id_negocio) 
                    VALUES (%s, %s, %s, %s)
                """, (marca, modelo, motor, current_user.id_negocio))
                conn.commit()
            flash(f'Vehículo {marca} {modelo} ({motor}) agregado con éxito.', 'success')
        except Exception as e:
            error_str = str(e).lower()
            if 'unique_vehiculo' in error_str or 'duplicate key' in error_str:
                flash(f'Ya existe el vehículo "{marca} {modelo} ({motor})".', 'error')
            else:
                flash('Error al guardar el vehículo.', 'error')

        return redirect(url_for('agregar_vehiculo'))

    with get_db() as (conn, cur):
        cur.execute("SELECT DISTINCT marca FROM vehiculo WHERE id_negocio = %s ORDER BY marca",
                    (current_user.id_negocio,))
        marcas_existentes = [r[0] for r in cur.fetchall()]
        
        cur.execute("SELECT DISTINCT modelo FROM vehiculo WHERE id_negocio = %s ORDER BY modelo",
                    (current_user.id_negocio,))
        modelos_existentes = [r[0] for r in cur.fetchall()]
        
        cur.execute("SELECT DISTINCT motor FROM vehiculo WHERE id_negocio = %s ORDER BY motor",
                    (current_user.id_negocio,))
        motores_existentes = [r[0] for r in cur.fetchall()]
        
        cur.execute("""SELECT id, marca, modelo, motor FROM vehiculo 
                    WHERE id_negocio = %s ORDER BY marca, modelo, motor""",
                    (current_user.id_negocio,))
        vehiculos = [{'id': v[0], 'marca': v[1], 'modelo': v[2], 'motor': v[3]}
                    for v in cur.fetchall()]

    return render_template('vehiculo.html',
                        marcas_existentes=marcas_existentes,
                        modelos_existentes=modelos_existentes,
                        motores_existentes=motores_existentes,
                        vehiculos=vehiculos)


# ---------- PRODUCTO BASE ----------

def to_numeric_or_none(value):
    return value if value != '' else None



@app.route('/producto_base', methods=['GET', 'POST'])
@login_required
def agregar_producto_base():
    if request.method == 'POST':

        # ===== OBTENER DATOS =====
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        alto = request.form.get('alto', '').strip()
        ancho = request.form.get('ancho', '').strip()
        largo = request.form.get('largo', '').strip()
        diametro = request.form.get('diametro', '').strip()
        
        # ===== VALIDACIÓN =====
        
        # 1. Nombre obligatorio
        if not nombre:
            flash('El campo "Nombre" es obligatorio.', 'error')
            return redirect(url_for('agregar_producto_base'))
        
        nombre = normalizar_texto(nombre)
        if not nombre or len(nombre.strip()) == 0:
            flash('El campo "Nombre" no puede contener solo espacios.', 'error')
            return redirect(url_for('agregar_producto_base'))
        
        # 2. Validar dimensiones (si se proporcionan, deben ser números válidos)
        alto_val = None
        ancho_val = None
        largo_val = None
        diametro_val = None
        
        # Validar alto
        if alto:
            try:
                alto_val = float(alto)
                if alto_val < 0:
                    flash('Alto no puede ser negativo.', 'error')
                    return redirect(url_for('agregar_producto_base'))
                if alto_val > 99999:
                    flash('Alto es demasiado grande.', 'error')
                    return redirect(url_for('agregar_producto_base'))
            except ValueError:
                flash('Alto debe ser un número válido.', 'error')
                return redirect(url_for('agregar_producto_base'))
        
        # Validar ancho
        if ancho:
            try:
                ancho_val = float(ancho)
                if ancho_val < 0:
                    flash('Ancho no puede ser negativo.', 'error')
                    return redirect(url_for('agregar_producto_base'))
                if ancho_val > 99999:
                    flash('Ancho es demasiado grande.', 'error')
                    return redirect(url_for('agregar_producto_base'))
            except ValueError:
                flash('Ancho debe ser un número válido.', 'error')
                return redirect(url_for('agregar_producto_base'))
        
        # Validar largo
        if largo:
            try:
                largo_val = float(largo)
                if largo_val < 0:
                    flash('Largo no puede ser negativo.', 'error')
                    return redirect(url_for('agregar_producto_base'))
                if largo_val > 99999:
                    flash('Largo es demasiado grande.', 'error')
                    return redirect(url_for('agregar_producto_base'))
            except ValueError:
                flash('Largo debe ser un número válido.', 'error')
                return redirect(url_for('agregar_producto_base'))

        # Validar diámetro
        if diametro:
            try:
                diametro_val = float(diametro)
                if diametro_val < 0:
                    flash('Diámetro no puede ser negativo.', 'error')
                    return redirect(url_for('agregar_producto_base'))
                if diametro_val > 99999:
                    flash('Diámetro es demasiado grande.', 'error')
                    return redirect(url_for('agregar_producto_base'))
            except ValueError:
                flash('Diámetro debe ser un número válido.', 'error')
                return redirect(url_for('agregar_producto_base'))

        
        # 3. Verificar duplicado
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id FROM producto_base 
            WHERE LOWER(nombre) = LOWER(%s) AND id_negocio = %s
        """, (nombre, current_user.id_negocio))

        if cur.fetchone():
            cur.close()
            conn.close()
            flash(f'Ya existe un producto base con el nombre "{nombre}".', 'error')
            return redirect(url_for('agregar_producto_base'))
    
        
        
        # ===== GUARDAR =====
        
        imagen_url = None
        
        # Procesar imagen si existe
        imagen = request.files.get('imagen')
        if imagen and imagen.filename:
            es_valida, resultado = validar_imagen(imagen)
            
            if not es_valida:
                # resultado es el mensaje de error
                flash(resultado, 'error')
                return redirect(url_for('agregar_producto_base'))
            
            # resultado son los bytes validados
            imagen_bytes = resultado
            
            try:
                import uuid
                supabase = get_supabase_client()
                extension = imagen.filename.rsplit('.', 1)[-1].lower()
                nombre_archivo = f"producto_{uuid.uuid4().hex}.{extension}"
                
                supabase.storage.from_('productos').upload(
                    nombre_archivo,
                    imagen_bytes,
                    {"content-type": f"image/{extension}"}
                )
                imagen_url = supabase.storage.from_('productos').get_public_url(nombre_archivo)
            except Exception as e:
                logger.error("Error al subir imagen: %s", type(e).__name__)
                # No fallar, solo no guardar imagen
        
        try:
            cur.execute("""
                INSERT INTO producto_base 
                (nombre, descripcion, alto, ancho, largo, diametro, imagen_url, id_negocio)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (nombre, descripcion or None, alto_val, ancho_val, largo_val, 
                diametro_val, imagen_url, current_user.id_negocio))
            
            conn.commit()
            flash(f'Producto base "{nombre}" creado correctamente.', 'success')
            
        except Exception as e:
            conn.rollback()
            flash(f'Error al guardar: {str(e)}', 'error')
        finally:
            cur.close()
            conn.close()

        
        return redirect(url_for('agregar_producto_base'))
    
    # GET
    return render_template('producto_base.html')


# --------- PRODUCTO BASE ↔ VEHICULO ----------



@app.route('/producto_vehiculo', methods=['GET', 'POST'])
@login_required
def asociar_producto_vehiculo():
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == 'POST':
        id_producto_variante = request.form['id_producto_variante']
        ids_vehiculos = request.form.getlist('vehiculos')

        asociados = 0
        ya_existian = 0
        
        for id_vehiculo in ids_vehiculos:
            cur.execute("""
                INSERT INTO producto_vehiculo (id_producto_variante, id_vehiculo)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id
            """, (id_producto_variante, id_vehiculo))
            
            # Si devolvió un ID, es porque se insertó (no existía)
            if cur.fetchone():
                asociados += 1
            else:
                ya_existian += 1

        conn.commit()
        
        # Mensaje informativo según el resultado
        if asociados > 0 and ya_existian > 0:
            mensaje = f'✓ {asociados} vehículo(s) asociado(s) correctamente. {ya_existian} ya estaba(n) asociado(s) previamente.'
        elif asociados > 0:
            mensaje = f'✓ {asociados} vehículo(s) asociado(s) correctamente.'
        else:
            mensaje = f'⚠️ Los {ya_existian} vehículo(s) seleccionado(s) ya estaban asociados a este producto.'
        
        # Recargar datos
        cur.execute("""
            SELECT 
                pv.id, 
                pb.nombre || ' - ' || pv.marca || 
                COALESCE(' (' || pv.calidad || ')', '') AS nombre_completo
            FROM producto_variante pv
            JOIN producto_base pb ON pb.id = pv.id_producto_base
            WHERE pv.id_negocio = %s
            ORDER BY pb.nombre, pv.marca
        """, (current_user.id_negocio,))
        productos = cur.fetchall()
        
        cur.execute("""
            SELECT id, marca, modelo, motor 
            FROM vehiculo 
            WHERE id_negocio = %s
            ORDER BY marca, modelo
        """, (current_user.id_negocio,))
        vehiculos = cur.fetchall()
        
        cur.close()
        conn.close()
        
        return render_template('producto_vehiculo.html',
                             productos=productos,
                             vehiculos=vehiculos,
                             mensaje_exito=mensaje)

    # GET
    cur.execute("""
        SELECT id, nombre, alto, ancho, largo, diametro 
        FROM producto_base 
        WHERE id_negocio = %s
        ORDER BY nombre
    """, (current_user.id_negocio,))
    productos = [formatear_producto_con_dimensiones(p) for p in cur.fetchall()]

    cur.execute("""
        SELECT id, marca, modelo, motor FROM vehiculo 
        WHERE id_negocio = %s
        ORDER BY marca, modelo
    """, (current_user.id_negocio,))
    vehiculos = cur.fetchall()
    
    cur.close()
    conn.close()

    return render_template('producto_vehiculo.html',
                         productos=productos,
                         vehiculos=vehiculos)



# ---------- PROVEEDORES ----------


@app.route('/proveedor', methods=['GET', 'POST'])
@login_required
def agregar_proveedor():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        contacto = request.form.get('contacto', '').strip()

        if not nombre or len(nombre.strip()) == 0:
            flash('El campo "Nombre" es obligatorio.', 'error')
            return redirect(url_for('agregar_proveedor'))

        try:
            with get_db() as (conn, cur):
                cur.execute("""
                    INSERT INTO proveedor (nombre, contacto, id_negocio) 
                    VALUES (%s, %s, %s)
                """, (nombre, contacto or None, current_user.id_negocio))
                conn.commit()
            flash(f'Proveedor "{nombre}" agregado con éxito.', 'success')
        except Exception as e:
            flash(f'Error al guardar proveedor: {str(e)}', 'error')

        return redirect(url_for('agregar_proveedor'))

    with get_db() as (conn, cur):
        cur.execute("""
            SELECT id, nombre, contacto, TO_CHAR(creado_en, 'DD/MM/YYYY')
            FROM proveedor 
            WHERE id_negocio = %s
            ORDER BY nombre
        """, (current_user.id_negocio,))
        proveedores = [{'id': p[0], 'nombre': p[1], 'contacto': p[2], 'fecha': p[3]}
                       for p in cur.fetchall()]

    return render_template('proveedor.html', proveedores=proveedores)
    



# ---------- PRODUCTO VARIANTE ----------


from psycopg2 import errors

@app.route('/producto_variante', methods=['GET', 'POST'])
@login_required
def agregar_producto_variante():
    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        
        # ===== OBTENER DATOS DEL FORMULARIO =====
        id_producto_base = request.form.get('id_producto_base', '').strip()
        marca = request.form.get('marca', '').strip()
        calidad = request.form.get('calidad', '').strip()
        codigo = request.form.get('codigo', '').strip()
        precio = request.form.get('precio', '').strip()
        precio_compra = request.form.get('precio_compra', '').strip()
        stock = request.form.get('stock', '').strip()
        stock_minimo = request.form.get('stock_minimo', '5').strip()
        ubicacion = request.form.get('ubicacion', '').strip()
        ids_proveedores = request.form.getlist('proveedores')
        
        # ===== FUNCIÓN AUXILIAR PARA RECARGAR =====
        def recargar_con_error(mensaje):
            cur.execute("""
                SELECT id, nombre FROM producto_base 
                WHERE id_negocio = %s
                ORDER BY nombre
            """, (current_user.id_negocio,))
            productos = cur.fetchall()
            cur.execute("""
                SELECT id, nombre FROM proveedor 
                WHERE id_negocio = %s
                ORDER BY nombre
            """, (current_user.id_negocio,))
            proveedores = cur.fetchall()
            cur.close()
            conn.close()
            return render_template('producto_variante.html',
                                 productos=productos,
                                 proveedores=proveedores,
                                 mensaje_error=mensaje)
        
        # ===== VALIDACIÓN BACKEND =====
        
        # 1. Producto base obligatorio
        if not id_producto_base:
            return recargar_con_error('Debe seleccionar un Producto Base.')
        
        # 2. Marca obligatoria y no vacía
        if not marca:
            return recargar_con_error('El campo "Marca" es obligatorio.')
        
        marca = normalizar_texto(marca)
        if not marca or len(marca.strip()) == 0:
            return recargar_con_error('El campo "Marca" no puede contener solo espacios.')
        
        # 3. Precio obligatorio y válido
        if not precio:
            return recargar_con_error('El campo "Precio de Venta" es obligatorio.')
        
        try:
            precio = float(precio)
            if precio < 0:
                return recargar_con_error('El precio de venta no puede ser negativo.')
            if precio > 9999999:
                return recargar_con_error('El precio de venta es demasiado alto.')
        except ValueError:
            return recargar_con_error('El precio de venta debe ser un número válido.')
        
        # 4. Precio de compra (opcional pero si existe debe ser válido)
        if precio_compra:
            try:
                precio_compra = float(precio_compra)
                if precio_compra < 0:
                    return recargar_con_error('El precio de compra no puede ser negativo.')
                if precio_compra > precio:
                    return recargar_con_error('El precio de compra no puede ser mayor al precio de venta.')
            except ValueError:
                return recargar_con_error('El precio de compra debe ser un número válido.')
        else:
            precio_compra = None
        
        # 5. Stock obligatorio y válido
        if not stock:
            return recargar_con_error('El campo "Stock" es obligatorio.')
        
        try:
            stock = int(stock)
            if stock < 0:
                return recargar_con_error('El stock no puede ser negativo.')
            if stock > 999999:
                return recargar_con_error('El stock es demasiado alto.')
        except ValueError:
            return recargar_con_error('El stock debe ser un número entero válido.')
        
        # 6. Stock mínimo válido
        try:
            stock_minimo = int(stock_minimo) if stock_minimo else 5
            if stock_minimo < 0:
                stock_minimo = 0
        except ValueError:
            stock_minimo = 5
        
        # 7. Verificar duplicado (mismo producto base + marca)
        cur.execute("""
            SELECT id FROM producto_variante 
            WHERE id_producto_base = %s AND LOWER(marca) = LOWER(%s)
            AND id_negocio = %s
        """, (id_producto_base, marca, current_user.id_negocio))
        
        if cur.fetchone():
            return recargar_con_error(f'Ya existe una variante con la marca "{marca}" para este producto.')
        
        # 8. Verificar que el producto base exista
        cur.execute("""
            SELECT id FROM producto_base 
            WHERE id = %s AND id_negocio = %s
        """, (id_producto_base, current_user.id_negocio))
        if not cur.fetchone():
            return recargar_con_error('El Producto Base seleccionado no existe.')
        
        # ===== TODO OK - GUARDAR =====
        
        try:
            # Insertar producto variante
            cur.execute("""
                INSERT INTO producto_variante 
                (id_producto_base, marca, calidad, codigo, precio, precio_compra, 
                stock, stock_minimo, ubicacion, activo, id_negocio)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                RETURNING id
            """, (id_producto_base, marca, calidad or None, codigo or None, 
                precio, precio_compra, stock, stock_minimo, ubicacion or None,
                current_user.id_negocio))
                        
            id_variante = cur.fetchone()[0]
            
            # Asociar proveedores
            for id_prov in ids_proveedores:
                cur.execute("""
                    INSERT INTO producto_proveedor (id_producto_variante, id_proveedor)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                """, (id_variante, id_prov))
            
            # Registrar movimiento inicial de stock
            registrar_movimiento_stock(
                cur,
                id_variante,
                'ingreso_inicial',
                stock,
                0,
                stock,
                'Stock inicial al crear producto',
                current_user.id,
                precio_compra=precio_compra,
                precio_venta=precio
            )
            
            conn.commit()
            
            flash(f'Producto variante "{marca}" creado correctamente con stock de {stock} unidades.', 'success')
            return redirect(url_for('agregar_producto_variante'))
            
        except Exception as e:
            conn.rollback()
            flash(f'Error al guardar el producto: {str(e)}', 'error')
            return redirect(url_for('agregar_producto_variante'))
        finally:
            cur.close()
            conn.close()
    
    # ===== GET: CARGAR FORMULARIO =====
    cur.execute("""
        SELECT id, nombre FROM producto_base 
        WHERE id_negocio = %s
        ORDER BY nombre
    """, (current_user.id_negocio,))
    productos = cur.fetchall()
    
    if not productos:
        cur.close()
        conn.close()
        return render_template('producto_variante.html',
                             productos=[],
                             proveedores=[],
                             mensaje_error='No hay productos base registrados. Creá uno primero.')
    
    cur.execute("""
        SELECT id, nombre FROM proveedor 
        WHERE id_negocio = %s
        ORDER BY nombre
    """, (current_user.id_negocio,))
    proveedores = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('producto_variante.html',
                         productos=productos,
                         proveedores=proveedores)


# ============ DAR DE BAJA / ACTIVAR PRODUCTO ============

@app.route('/producto/desactivar/<int:id_producto>')
@login_required
def desactivar_producto(id_producto):
    try:
        with get_db() as (conn, cur):
            cur.execute("""
                SELECT pb.nombre, pv.marca FROM producto_variante pv
                JOIN producto_base pb ON pb.id = pv.id_producto_base
                WHERE pv.id = %s AND pv.id_negocio = %s
            """, (id_producto, current_user.id_negocio))
            producto = cur.fetchone()
            nombre = f"{producto[0]} - {producto[1]}" if producto else "Producto"
            cur.execute("""
                UPDATE producto_variante SET activo = FALSE 
                WHERE id = %s AND id_negocio = %s
            """, (id_producto, current_user.id_negocio))
            conn.commit()
        flash(f'Producto "{nombre}" desactivado correctamente.', 'success')
    except Exception as e:
        flash(f'Error al desactivar el producto: {str(e)}', 'error')
    return redirect(url_for('listar_productos'))


@app.route('/producto/activar/<int:id_producto>')
@login_required
def activar_producto(id_producto):
    try:
        with get_db() as (conn, cur):
            cur.execute("""
                SELECT pb.nombre, pv.marca FROM producto_variante pv
                JOIN producto_base pb ON pb.id = pv.id_producto_base
                WHERE pv.id = %s AND pv.id_negocio = %s
            """, (id_producto, current_user.id_negocio))
            producto = cur.fetchone()
            nombre = f"{producto[0]} - {producto[1]}" if producto else "Producto"
            cur.execute("""
                UPDATE producto_variante SET activo = TRUE 
                WHERE id = %s AND id_negocio = %s
            """, (id_producto, current_user.id_negocio))
            conn.commit()
        flash(f'Producto "{nombre}" activado correctamente.', 'success')
    except Exception as e:
        flash(f'Error al activar el producto: {str(e)}', 'error')
    return redirect(url_for('listar_productos'))

# ------------------ VENTA ------------------------------


@app.route('/venta', methods=['GET', 'POST'])
@login_required
def agregar_venta():
    conn = get_db_connection()
    cur = conn.cursor()
 
    if request.method == 'POST':
        id_cliente = request.form['id_cliente'] or None
        tipo_pago = request.form.get('tipo_pago', 'contado')
        metodo_pago = request.form.get('metodo_pago', 'efectivo')
 
        # ===== FASE 1: RECOLECTAR Y VALIDAR TODO EL CARRITO (sin tocar la DB) =====
 
        if tipo_pago == 'cuenta_corriente' and not id_cliente:
            # recargar formulario con error
            cur.execute("SELECT id, nombre FROM cliente WHERE id_negocio = %s ORDER BY nombre", 
                        (current_user.id_negocio,))
            clientes = cur.fetchall()
            cur.execute("""
                SELECT pv.id, pb.nombre, pv.marca,
                    pb.alto, pb.ancho, pb.largo, pb.diametro
                FROM producto_variante pv
                JOIN producto_base pb ON pb.id = pv.id_producto_base
                WHERE pv.activo = TRUE AND pv.id_negocio = %s
                ORDER BY pb.nombre, pv.marca
            """, (current_user.id_negocio,))
            productos = []
            for p in cur.fetchall():
                if any([p[3], p[4], p[5], p[6]]):
                    display = f"{p[1]} ({p[3] or ''}x{p[4] or ''}x{p[5] or ''}x{p[6] or ''}) - {p[2]}"
                else:
                    display = f"{p[1]} - {p[2]}"
                productos.append((p[0], display))
            cur.close()
            conn.close()
            return render_template('venta.html',
                                clientes=clientes,
                                productos=productos,
                                mensaje_error='Para cuenta corriente necesitás seleccionar un cliente.')
 
        productos_enviados = {}
        for key in request.form.keys():
            if key.startswith('producto_'):
                index = key.split('_')[1]
                productos_enviados[index] = {
                    'producto': request.form.get(f'producto_{index}'),
                    'cantidad': request.form.get(f'cantidad_{index}')
                }
 
        # Filtrar entradas vacías
        items_validos = [
            (datos['producto'], datos['cantidad'])
            for datos in productos_enviados.values()
            if datos['producto'] and datos['cantidad']
        ]
 
        if not items_validos:
            cur.execute("""
                SELECT id, nombre FROM cliente 
                WHERE id_negocio = %s
                ORDER BY nombre
            """, (current_user.id_negocio,))
            clientes = cur.fetchall()
            cur.execute("""
                SELECT pv.id, pb.nombre, pv.marca,
                    pb.alto, pb.ancho, pb.largo, pb.diametro
                FROM producto_variante pv
                JOIN producto_base pb ON pb.id = pv.id_producto_base
                WHERE pv.activo = TRUE AND pv.id_negocio = %s
                ORDER BY pb.nombre, pv.marca
            """, (current_user.id_negocio,))
            productos = []
            for p in cur.fetchall():
                if any([p[3], p[4], p[5], p[6]]):
                    display = f"{p[1]} ({p[3] or ''}x{p[4] or ''}x{p[5] or ''}x{p[6] or ''}) - {p[2]}"
                else:
                    display = f"{p[1]} - {p[2]}"
                productos.append((p[0], display))
            cur.close()
            conn.close()
            return render_template('venta.html',
                                   clientes=clientes,
                                   productos=productos,
                                   mensaje_error='No se puede registrar una venta sin productos.')
 
        # Validar stock de cada item ANTES de crear nada
        items_procesables = []
        for id_producto, cantidad in items_validos:         # ← loop de VALIDACIÓN
            cantidad_int = int(cantidad)
 
            cur.execute("""
                SELECT pv.precio, pv.precio_compra, pv.stock,
                    pb.nombre, pv.marca
                FROM producto_variante pv
                JOIN producto_base pb ON pb.id = pv.id_producto_base
                WHERE pv.id = %s AND pv.activo = TRUE AND pv.id_negocio = %s
            """, (id_producto, current_user.id_negocio))
            row = cur.fetchone()
 
            if not row:
                continue
 
            precio_unitario = row[0]
            precio_compra = row[1]
            stock_actual = row[2]
            producto_nombre = f"{row[3]} - {row[4]}"
 
            if stock_actual < cantidad_int:
                cur.execute("""
                    SELECT id, nombre FROM cliente 
                    WHERE id_negocio = %s
                    ORDER BY nombre
                """, (current_user.id_negocio,))
                clientes = cur.fetchall()
                cur.execute("""
                    SELECT pv.id, pb.nombre, pv.marca,
                        pb.alto, pb.ancho, pb.largo, pb.diametro
                    FROM producto_variante pv
                    JOIN producto_base pb ON pb.id = pv.id_producto_base
                    WHERE pv.activo = TRUE AND pv.id_negocio = %s
                    ORDER BY pb.nombre, pv.marca
                """, (current_user.id_negocio,))
                productos = []
                for p in cur.fetchall():
                    if any([p[3], p[4], p[5], p[6]]):
                        display = f"{p[1]} ({p[3] or ''}x{p[4] or ''}x{p[5] or ''}x{p[6] or ''}) - {p[2]}"
                    else:
                        display = f"{p[1]} - {p[2]}"
                    productos.append((p[0], display))
                cur.close()
                conn.close()
                return render_template('venta.html',
                                       clientes=clientes,
                                       productos=productos,
                                       mensaje_error=f'Stock insuficiente para {producto_nombre}. '
                                                     f'Disponible: {stock_actual}, solicitado: {cantidad_int}')
 
            items_procesables.append({
                'id_producto': id_producto,
                'cantidad': cantidad_int,
                'precio_unitario': precio_unitario,
                'precio_compra': precio_compra,
                'producto_nombre': producto_nombre,
            })
        # ← acá termina el loop de validación
 
        # ===== FASE 2: TODO VALIDADO — recién ahora creamos la venta =====
 
        cur.execute("""
            INSERT INTO venta (id_cliente, total, id_negocio, tipo_pago, metodo_pago) 
            VALUES (%s, 0, %s, %s, %s) RETURNING id
        """, (id_cliente, current_user.id_negocio, tipo_pago, metodo_pago))
        id_venta = cur.fetchone()[0]
 
        total = 0
 
        for item in items_procesables:                      # ← loop de ESCRITURA
            id_producto = item['id_producto']
            cantidad_int = item['cantidad']
            precio_unitario = item['precio_unitario']
            precio_compra_producto = item['precio_compra']
 
            cur.execute("""
                UPDATE producto_variante
                SET stock = stock - %s
                WHERE id = %s AND stock >= %s
                RETURNING stock
            """, (cantidad_int, id_producto, cantidad_int))
 
            resultado = cur.fetchone()
 
            if not resultado:
                continue
 
            nuevo_stock = resultado[0]
            stock_antes = nuevo_stock + cantidad_int
 
            cur.execute("""
                INSERT INTO venta_detalle
                (id_venta, id_producto_variante, cantidad, precio_unitario, precio_compra)
                VALUES (%s, %s, %s, %s, %s)
            """, (id_venta, id_producto, cantidad_int, precio_unitario, precio_compra_producto))
 
            registrar_movimiento_stock(
                cur,
                id_producto,
                'venta',
                cantidad_int,
                stock_antes,
                nuevo_stock,
                f'Venta #{id_venta}',
                current_user.id,
                precio_compra=precio_compra_producto,
                precio_venta=precio_unitario
            )
 
            total += precio_unitario * cantidad_int
        # ← acá termina el loop de escritura
 
        cur.execute(
            "UPDATE venta SET total = %s WHERE id = %s",
            (total, id_venta)
        )
 
        if tipo_pago == 'cuenta_corriente' and id_cliente:
            # Verificar si ya tiene cuenta corriente
            cur.execute("""
                SELECT id FROM cuenta_corriente 
                WHERE id_cliente = %s AND id_negocio = %s
            """, (id_cliente, current_user.id_negocio))
            cuenta = cur.fetchone()
            
            if not cuenta:
                # Crear cuenta corriente nueva
                cur.execute("""
                    INSERT INTO cuenta_corriente (id_cliente, id_negocio, saldo)
                    VALUES (%s, %s, %s)
                """, (id_cliente, current_user.id_negocio, total))
            else:
                # Sumar al saldo existente
                cur.execute("""
                    UPDATE cuenta_corriente 
                    SET saldo = saldo + %s
                    WHERE id_cliente = %s AND id_negocio = %s
                """, (total, id_cliente, current_user.id_negocio))
            
            # Registrar movimiento
            cur.execute("""
                INSERT INTO movimiento_cuenta 
                (id_cliente, id_negocio, tipo, monto, descripcion, id_venta)
                VALUES (%s, %s, 'cargo', %s, %s, %s)
            """, (id_cliente, current_user.id_negocio, total, 
                f'Venta #{id_venta}', id_venta))
 
        conn.commit()
        cur.close()
        conn.close()
 
        return redirect(url_for('listar_ventas_app'))
 
    # -------- GET --------
 
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT id, nombre FROM cliente 
            WHERE id_negocio = %s
            ORDER BY nombre
        """, (current_user.id_negocio,))
        clientes = cur.fetchall()
        cur.execute("""
            SELECT pv.id, pb.nombre, pv.marca,
                pb.alto, pb.ancho, pb.largo, pb.diametro
            FROM producto_variante pv
            JOIN producto_base pb ON pb.id = pv.id_producto_base
            WHERE pv.activo = TRUE AND pv.id_negocio = %s
            ORDER BY pb.nombre, pv.marca
        """, (current_user.id_negocio,))
        productos = []
        for p in cur.fetchall():
            if any([p[3], p[4], p[5], p[6]]):
                display = f"{p[1]} ({p[3] or ''}x{p[4] or ''}x{p[5] or ''}x{p[6] or ''}) - {p[2]}"
            else:
                display = f"{p[1]} - {p[2]}"
            productos.append((p[0], display))
 
    if not productos:
        return render_template('venta.html', clientes=clientes, productos=[],
                            mensaje_error='No hay productos cargados todavía. Agregá productos primero desde "Producto Base" y "Nueva Variante".')
 
    return render_template('venta.html', clientes=clientes, productos=productos)

# ----------------- LISTADO VENTA ------------------


@app.route('/ventas')
@login_required
def listar_ventas_app():
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT v.id, v.fecha,
                COALESCE(c.nombre, 'Mostrador') AS cliente,
                v.total, v.anulada, v.tipo_pago, v.metodo_pago
            FROM venta v
            LEFT JOIN cliente c ON c.id = v.id_cliente
            WHERE v.id_negocio = %s
            ORDER BY v.fecha DESC
        """, (current_user.id_negocio,))
        ventas = []
        for r in cur.fetchall():
            ventas.append({
                "id": r[0],
                "fecha": r[1].strftime("%d/%m/%Y %H:%M"),
                "cliente": r[2],
                "total": f"{r[3]:.2f}",
                "anulada": r[4],
                "tipo_pago": r[5],
                "metodo_pago": r[6] or 'efectivo',
            })
    return render_template('ventas.html', ventas=ventas)


# ------------------- DETALLE VENTA ---------------------


@app.route('/venta/<int:id_venta>')
@login_required
def ver_detalle_venta(id_venta):
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT v.id, v.fecha, COALESCE(c.nombre, 'Mostrador'), v.total,
                   v.anulada, v.fecha_anulacion, v.motivo_anulacion,
                   v.tipo_pago, v.id_cliente,
                   u.nombre AS anulada_por
            FROM venta v
            LEFT JOIN cliente c ON c.id = v.id_cliente
            LEFT JOIN usuario u ON u.id = v.anulada_por_usuario_id
            WHERE v.id = %s AND v.id_negocio = %s
        """, (id_venta, current_user.id_negocio))
        v = cur.fetchone()
 
        if not v:
            return render_template('404.html',
                                mensaje=f'La venta #{id_venta} no existe.'), 404
 
        venta = {
            'id': v[0],
            'fecha': v[1].strftime("%d/%m/%Y %H:%M"),
            'cliente': v[2],
            'total': f"{v[3]:.2f}",
            'anulada': v[4],
            'fecha_anulacion': v[5].strftime("%d/%m/%Y %H:%M") if v[5] else None,
            'motivo_anulacion': v[6],
            'tipo_pago': v[7],
            'id_cliente': v[8],
            'anulada_por': v[9],
        }
 
        cur.execute("""
            SELECT pb.nombre, pv.marca,
                   pb.alto, pb.ancho, pb.largo, pb.diametro,
                   vd.cantidad, vd.precio_unitario,
                   vd.cantidad * vd.precio_unitario AS subtotal
            FROM venta_detalle vd
            JOIN producto_variante pv ON pv.id = vd.id_producto_variante
            JOIN producto_base pb ON pb.id = pv.id_producto_base
            WHERE vd.id_venta = %s
        """, (id_venta,))
 
        detalles = []
        for r in cur.fetchall():
            if any([r[2], r[3], r[4], r[5]]):
                display = f"{r[0]} ({r[2] or ''}x{r[3] or ''}x{r[4] or ''}x{r[5] or ''}) - {r[1]}"
            else:
                display = f"{r[0]} - {r[1]}"
            detalles.append({
                'producto': display,
                'cantidad': r[6],
                'precio_unitario': f"{r[7]:.2f}",
                'subtotal': f"{r[8]:.2f}"
            })
 
    return render_template('detalle_venta.html', venta=venta, detalles=detalles)



# ------------------- ANULAR VENTA ---------------------

@app.route('/venta/<int:id_venta>/anular', methods=['POST'])
@login_required
def anular_venta(id_venta):
    motivo = request.form.get('motivo', '').strip()
 
    if not motivo:
        flash('Tenés que ingresar un motivo para anular la venta.', 'error')
        return redirect(url_for('ver_detalle_venta', id_venta=id_venta))
 
    try:
        with get_db() as (conn, cur):
 
            # 1. Buscar la venta y verificar que pertenece a este negocio
            cur.execute("""
                SELECT id, total, anulada, tipo_pago, id_cliente
                FROM venta
                WHERE id = %s AND id_negocio = %s
            """, (id_venta, current_user.id_negocio))
            venta = cur.fetchone()
 
            if not venta:
                flash('La venta no existe.', 'error')
                return redirect(url_for('listar_ventas_app'))
 
            if venta[2]:  # ya estaba anulada
                flash('Esta venta ya fue anulada anteriormente.', 'error')
                return redirect(url_for('ver_detalle_venta', id_venta=id_venta))
 
            total_venta = venta[1]
            tipo_pago   = venta[3]
            id_cliente  = venta[4]
 
            # 2. Obtener todos los ítems de la venta
            cur.execute("""
                SELECT id_producto_variante, cantidad, precio_unitario, precio_compra
                FROM venta_detalle
                WHERE id_venta = %s
            """, (id_venta,))
            items = cur.fetchall()
 
            # 3. Para cada ítem: devolver stock y registrar movimiento
            for item in items:
                id_producto    = item[0]
                cantidad       = item[1]
                precio_venta   = item[2]
                precio_compra  = item[3]
 
                # Obtener stock actual antes de restaurar
                cur.execute(
                    "SELECT stock FROM producto_variante WHERE id = %s",
                    (id_producto,)
                )
                row = cur.fetchone()
                if not row:
                    continue  # el producto fue eliminado, saltear
 
                stock_antes  = row[0]
                stock_despues = stock_antes + cantidad
 
                # Restaurar stock
                cur.execute("""
                    UPDATE producto_variante
                    SET stock = stock + %s
                    WHERE id = %s
                """, (cantidad, id_producto))
 
                # Registrar en movimiento_stock
                registrar_movimiento_stock(
                    cur,
                    id_producto,
                    'anulacion_venta',
                    cantidad,
                    stock_antes,
                    stock_despues,
                    motivo=f'Anulación venta #{id_venta}: {motivo}',
                    id_usuario=current_user.id,
                    precio_compra=precio_compra,
                    precio_venta=precio_venta
                )
 
            # 4. Si era cuenta corriente, descontar el saldo del cliente
            if tipo_pago == 'cuenta_corriente' and id_cliente:
                cur.execute("""
                    UPDATE cuenta_corriente
                    SET saldo = GREATEST(saldo - %s, 0)
                    WHERE id_cliente = %s AND id_negocio = %s
                """, (total_venta, id_cliente, current_user.id_negocio))
 
                # Registrar movimiento en cuenta corriente
                cur.execute("""
                    INSERT INTO movimiento_cuenta
                    (id_cliente, id_negocio, tipo, monto, descripcion, id_venta)
                    VALUES (%s, %s, 'anulacion', %s, %s, %s)
                """, (
                    id_cliente,
                    current_user.id_negocio,
                    total_venta,
                    f'Anulación venta #{id_venta}: {motivo}',
                    id_venta
                ))
 
            # 5. Marcar la venta como anulada
            cur.execute("""
                UPDATE venta
                SET anulada             = TRUE,
                    fecha_anulacion     = NOW(),
                    motivo_anulacion    = %s,
                    anulada_por_usuario_id = %s
                WHERE id = %s
            """, (motivo, current_user.id, id_venta))
 
            conn.commit()
 
        flash(f'La venta #{id_venta} fue anulada correctamente. El stock fue restaurado.', 'success')
 
    except Exception as e:
        logger.error(f"Error al anular venta {id_venta}: {e}")
        flash(f'Ocurrió un error al anular la venta: {str(e)}', 'error')
 
    return redirect(url_for('ver_detalle_venta', id_venta=id_venta))



# --------------- REPORTE PRODUCTOS --------------


@app.route("/productos")
@login_required
def listar_productos():
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT pv.id, pb.nombre, pb.descripcion,
                pb.alto, pb.ancho, pb.largo, pb.diametro,
                pv.marca, pv.calidad, pv.subcodigo,
                pv.precio, pv.precio_compra, pv.stock,
                pv.stock_minimo, pv.ubicacion, pb.imagen_url,
                pv.codigo, pv.activo, pv.pedido_activo,
                pv.pedido_cantidad,
                TO_CHAR(pv.pedido_fecha, 'DD/MM/YYYY'),
                TO_CHAR(pv.pedido_fecha_estimada, 'DD/MM/YYYY'),
                (
                    SELECT STRING_AGG(pr.nombre, ', ' ORDER BY pr.nombre)
                    FROM producto_proveedor pp
                    JOIN proveedor pr ON pr.id = pp.id_proveedor
                    WHERE pp.id_producto_variante = pv.id
                )
            FROM producto_variante pv
            JOIN producto_base pb ON pb.id = pv.id_producto_base
            WHERE pv.id_negocio = %s
            ORDER BY pv.activo DESC, pb.nombre, pv.marca
        """, (current_user.id_negocio,))
        productos = []
        for r in cur.fetchall():
            alto, ancho, largo, diametro = r[3], r[4], r[5], r[6]
            dimensiones = None
            if any([alto, ancho, largo, diametro]):
                dimensiones = f"{alto or ''}x{ancho or ''}x{largo or ''}x{diametro or ''}"
            productos.append({
                "id": r[0], "producto": r[1], "descripcion": r[2],
                "dimensiones": dimensiones, "marca": r[7], "calidad": r[8],
                "subcodigo": r[9], "precio": f"{r[10]:.2f}",
                "precio_compra": f"{r[11]:.2f}" if (r[11] and current_user.es_admin()) else None,
                "stock": r[12], "stock_minimo": r[13], "ubicacion": r[14],
                "imagen_url": r[15], "codigo": r[16], "activo": r[17],
                "pedido_activo": r[18], "pedido_cantidad": r[19],
                "pedido_fecha": r[20], "pedido_fecha_estimada": r[21],
                "proveedor": r[22]
            })
    return render_template('productos.html', productos=productos)


# ============ GESTIÓN DE PEDIDOS ============

@app.route('/producto/marcar_pedido', methods=['POST'])
@login_required
def marcar_pedido():
    id_producto = request.form['id_producto']
    cantidad = request.form['cantidad']
    try:
        with get_db() as (conn, cur):
            cur.execute("""
                UPDATE producto_variante
                SET pedido_activo = TRUE, pedido_cantidad = %s
                WHERE id = %s AND id_negocio = %s
            """, (cantidad, id_producto, current_user.id_negocio))
            cur.execute("""
                SELECT pb.nombre, pv.marca FROM producto_variante pv
                JOIN producto_base pb ON pb.id = pv.id_producto_base
                WHERE pv.id = %s AND pv.id_negocio = %s
            """, (id_producto, current_user.id_negocio))
            producto = cur.fetchone()
            nombre = f"{producto[0]} - {producto[1]}" if producto else "Producto"
            conn.commit()
        flash(f'Pedido de {cantidad} unidades de "{nombre}" marcado correctamente.', 'success')
    except Exception as e:
        flash(f'Error al marcar el pedido: {str(e)}', 'error')
    return redirect(url_for('listar_productos'))



@app.route('/producto/recibir_pedido', methods=['POST'])
@login_required
def recibir_pedido():
    id_producto = request.form['id_producto']
    cantidad_recibida = int(request.form['cantidad_recibida'])
    try:
        with get_db() as (conn, cur):
            cur.execute("""
                SELECT pv.stock, pb.nombre, pv.marca, pv.precio_compra, pv.precio
                FROM producto_variante pv
                JOIN producto_base pb ON pb.id = pv.id_producto_base
                WHERE pv.id = %s AND pv.id_negocio = %s
            """, (id_producto, current_user.id_negocio))
            row = cur.fetchone()
            stock_actual = row[0]
            nombre = f"{row[1]} - {row[2]}"
            nuevo_stock = stock_actual + cantidad_recibida

            cur.execute("""
                UPDATE producto_variante
                SET stock = %s, pedido_activo = FALSE, pedido_cantidad = NULL
                WHERE id = %s AND id_negocio = %s
            """, (nuevo_stock, id_producto, current_user.id_negocio))

            registrar_movimiento_stock(
                cur, id_producto, 'recepcion_pedido',
                cantidad_recibida, stock_actual, nuevo_stock,
                'Recepción de pedido', current_user.id,
                precio_compra=row[3], precio_venta=row[4]
            )
            conn.commit()
        flash(f'Pedido de "{nombre}" recibido. Stock: {nuevo_stock} unidades.', 'success')
    except Exception as e:
        flash(f'Error al recibir el pedido: {str(e)}', 'error')
    return redirect(url_for('listar_productos'))

# ------------ MOSTRAR STOCK BAJO --------------------

@app.route("/stock-bajo")
@login_required
def stock_bajo():
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT COALESCE(pb.nombre, 'producto sin base'),
                pv.marca, pv.calidad, pv.stock, pv.ubicacion, pv.stock_minimo
            FROM producto_variante pv
            LEFT JOIN producto_base pb ON pb.id = pv.id_producto_base
            WHERE pv.stock <= pv.stock_minimo 
            AND pv.activo = TRUE
            AND pv.id_negocio = %s
            ORDER BY pv.stock ASC, pb.nombre
        """, (current_user.id_negocio,))
        productos = [{'producto': r[0], 'marca': r[1], 'calidad': r[2],
                      'stock': r[3], 'ubicacion': r[4], 'stock_minimo': r[5]}
                     for r in cur.fetchall()]
    return render_template('stock_bajo.html', productos=productos)

# ------------ PDF STOCK BAJO --------------------
 
@app.route("/stock-bajo/pdf")
@login_required
def pdf_stock_bajo():
    if 'pdf_stock_bajo' not in get_features(current_user.id_negocio):
        return jsonify({'error': 'No autorizado'}), 403
 
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from io import BytesIO
    from datetime import datetime
    from flask import make_response
 
    # Obtener nombre del negocio
    with get_db() as (conn, cur):
        cur.execute("SELECT nombre FROM negocio WHERE id = %s", (current_user.id_negocio,))
        negocio = cur.fetchone()
        nombre_negocio = negocio[0] if negocio else 'Mi Negocio'
 
        cur.execute("""
            SELECT COALESCE(pb.nombre, 'Producto sin base'),
                pv.marca, pv.calidad, pv.stock, pv.stock_minimo, pv.ubicacion
            FROM producto_variante pv
            LEFT JOIN producto_base pb ON pb.id = pv.id_producto_base
            WHERE pv.stock <= pv.stock_minimo
            AND pv.activo = TRUE
            AND pv.id_negocio = %s
            ORDER BY pv.stock ASC, pb.nombre
        """, (current_user.id_negocio,))
        productos = cur.fetchall()
 
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )
 
    styles = getSampleStyleSheet()
    elementos = []
 
    # Título
    estilo_titulo = ParagraphStyle(
        'titulo',
        parent=styles['Title'],
        fontSize=18,
        spaceAfter=4,
        alignment=TA_LEFT
    )
    estilo_subtitulo = ParagraphStyle(
        'subtitulo',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#6B7280'),
        spaceAfter=20,
        alignment=TA_LEFT
    )
 
    elementos.append(Paragraph(nombre_negocio, estilo_titulo))
    elementos.append(Paragraph(
        f"Pedido a Proveedor — Stock Bajo · {datetime.now().strftime('%d/%m/%Y')}",
        estilo_subtitulo
    ))
 
    if not productos:
        elementos.append(Paragraph("No hay productos con stock bajo en este momento.", styles['Normal']))
    else:
        # Tabla
        encabezado = ['Producto', 'Marca', 'Calidad', 'Stock Actual', 'Stock Mínimo', 'Cant. a Pedir', 'Ubicación']
        datos = [encabezado]
 
        for p in productos:
            nombre, marca, calidad, stock, stock_minimo, ubicacion = p
            cant_sugerida = max(0, (stock_minimo * 2) - stock)
            datos.append([
                nombre or '-',
                marca or '-',
                calidad or '-',
                str(stock),
                str(stock_minimo),
                str(cant_sugerida),
                ubicacion or '-'
            ])
 
        tabla = Table(datos, repeatRows=1, colWidths=[4.5*cm, 2.5*cm, 2*cm, 2*cm, 2*cm, 2*cm, 2.5*cm])
        tabla.setStyle(TableStyle([
            # Encabezado
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F2937')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            # Filas
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (3, 1), (5, -1), 'CENTER'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FAFB')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
 
        elementos.append(tabla)
        elementos.append(Spacer(1, 0.5*cm))
 
        # Nota al pie
        estilo_nota = ParagraphStyle(
            'nota',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#9CA3AF'),
        )
        elementos.append(Paragraph(
            "* La columna 'Cant. a Pedir' es una sugerencia calculada automáticamente. Podés ajustarla a mano antes de enviar.",
            estilo_nota
        ))
 
    doc.build(elementos)
    buffer.seek(0)
 
    response = make_response(buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=pedido_stock_bajo_{datetime.now().strftime("%Y%m%d")}.pdf'
    return response

# ------------------- MÓDULO CAJA / TALLER---------------
 
@app.route("/taller")
@login_required
def taller():
    if 'modulo_caja' not in get_features(current_user.id_negocio):
        return redirect(url_for('home'))
 
    from datetime import date
    hoy = date.today()
    desde = request.args.get('desde')
    hasta = request.args.get('hasta')
 
    with get_db() as (conn, cur):
        condiciones = ['id_negocio = %s']
        params = [current_user.id_negocio]
 
        if desde:
            condiciones.append('fecha >= %s')
            params.append(desde)
        if hasta:
            condiciones.append('fecha <= %s')
            params.append(hasta)
        if not desde and not hasta:
            condiciones.append("DATE_TRUNC('month', fecha) = DATE_TRUNC('month', CURRENT_DATE)")
 
        where = ' AND '.join(condiciones)
        cur.execute(f'''
            SELECT id, origen, cliente, descripcion, monto, metodo_pago, fecha
            FROM caja_registro
            WHERE {where}
            AND anulado = FALSE
            ORDER BY fecha DESC, id DESC
        ''', params)
        registros = [
            {
                'id': r[0], 'origen': r[1], 'cliente': r[2],
                'descripcion': r[3], 'monto': r[4],
                'metodo_pago': r[5], 'fecha': r[6],
            }
            for r in cur.fetchall()
        ]
 
    metodos = ['efectivo', 'transferencia', 'tarjeta_credito', 'tarjeta_debito']
    total = sum(r['monto'] for r in registros)
    por_metodo = {}
    for m in metodos:
        subtotal = sum(r['monto'] for r in registros if r['metodo_pago'] == m)
        if subtotal > 0:
            por_metodo[m] = subtotal
 
    resumen = {
        'taller': {'total': total, 'por_metodo': por_metodo}
    }
 
    return render_template('caja.html',
        registros=registros,
        resumen=resumen,
        desde=desde,
        hasta=hasta,
        hoy=hoy.strftime('%Y-%m-%d')
    )
 
 
@app.route("/taller/registrar", methods=['POST'])
@login_required
def taller_registrar():
    if 'modulo_caja' not in get_features(current_user.id_negocio):
        return redirect(url_for('home'))
 
    origen = request.form.get('origen')
    cliente = request.form.get('cliente', '').strip() or None
    descripcion = request.form.get('descripcion', '').strip() or None
    monto = request.form.get('monto')
    metodo_pago = request.form.get('metodo_pago')
    fecha = request.form.get('fecha')
 
    try:
        with get_db() as (conn, cur):
            cur.execute("""
                INSERT INTO caja_registro (id_negocio, origen, cliente, descripcion, monto, metodo_pago, fecha)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (current_user.id_negocio, origen, cliente, descripcion, float(monto), metodo_pago, fecha))
            conn.commit()
        flash('Cobro registrado correctamente.', 'success')
    except Exception as e:
        flash(f'Error al registrar el cobro: {str(e)}', 'error')
 
    mes = fecha[:7] if fecha else ''
    return redirect(url_for('taller', mes=mes))
 
 
@app.route("/taller/anular/<int:id>", methods=['POST'])
@login_required
def taller_anular(id):
    if 'modulo_caja' not in get_features(current_user.id_negocio):
        return jsonify({'ok': False}), 403
    try:
        with get_db() as (conn, cur):
            cur.execute("""
                UPDATE caja_registro SET anulado = TRUE WHERE id = %s AND id_negocio = %s
            """, (id, current_user.id_negocio))
            conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

# ------------------- PRODUCTOS MÁS VENDIDOS ---------------

@app.route("/productos-mas-vendidos")
@login_required
def productos_mas_vendidos():
    with get_db() as (conn, cur):

        # Top 5 más rentables (solo productos con precio de compra cargado)
        cur.execute("""
            SELECT
                pv.id,
                COALESCE(pb.nombre, 'Producto sin base') || ' - ' ||
                COALESCE(pv.marca, 'Sin marca')                        AS producto,
                SUM(vd.cantidad)                                        AS cantidad_vendida,
                SUM(vd.cantidad * vd.precio_unitario)                  AS total_facturado,
                SUM(vd.cantidad * (vd.precio_unitario - vd.precio_compra)) AS ganancia_total,
                CASE
                    WHEN SUM(vd.cantidad * vd.precio_unitario) > 0
                    THEN ROUND(
                        SUM(vd.cantidad * (vd.precio_unitario - vd.precio_compra)) * 100.0 /
                        SUM(vd.cantidad * vd.precio_unitario), 1
                    )
                    ELSE 0
                END                                                     AS margen_pct
            FROM venta_detalle vd
            JOIN venta v ON v.id = vd.id_venta
            LEFT JOIN producto_variante pv ON pv.id = vd.id_producto_variante
            LEFT JOIN producto_base pb ON pb.id = pv.id_producto_base
            WHERE pv.id_negocio = %s
              AND v.anulada = FALSE
              AND vd.precio_compra IS NOT NULL
            GROUP BY pv.id, pb.nombre, pv.marca
            ORDER BY ganancia_total DESC
            LIMIT 5
        """, (current_user.id_negocio,))
        top_rentables = [
            {
                'id': r[0],
                'producto': r[1],
                'cantidad_vendida': r[2],
                'total_facturado': f"{r[3]:.2f}",
                'ganancia_total': f"{r[4]:.2f}",
                'margen_pct': r[5],
            }
            for r in cur.fetchall()
        ]

        # Top 5 menos rentables (solo productos con precio de compra cargado)
        cur.execute("""
            SELECT
                pv.id,
                COALESCE(pb.nombre, 'Producto sin base') || ' - ' ||
                COALESCE(pv.marca, 'Sin marca')                        AS producto,
                SUM(vd.cantidad)                                        AS cantidad_vendida,
                SUM(vd.cantidad * vd.precio_unitario)                  AS total_facturado,
                SUM(vd.cantidad * (vd.precio_unitario - vd.precio_compra)) AS ganancia_total,
                CASE
                    WHEN SUM(vd.cantidad * vd.precio_unitario) > 0
                    THEN ROUND(
                        SUM(vd.cantidad * (vd.precio_unitario - vd.precio_compra)) * 100.0 /
                        SUM(vd.cantidad * vd.precio_unitario), 1
                    )
                    ELSE 0
                END                                                     AS margen_pct
            FROM venta_detalle vd
            JOIN venta v ON v.id = vd.id_venta
            LEFT JOIN producto_variante pv ON pv.id = vd.id_producto_variante
            LEFT JOIN producto_base pb ON pb.id = pv.id_producto_base
            WHERE pv.id_negocio = %s
              AND v.anulada = FALSE
              AND vd.precio_compra IS NOT NULL
            GROUP BY pv.id, pb.nombre, pv.marca
            ORDER BY ganancia_total ASC
            LIMIT 5
        """, (current_user.id_negocio,))
        menos_rentables = [
            {
                'id': r[0],
                'producto': r[1],
                'cantidad_vendida': r[2],
                'total_facturado': f"{r[3]:.2f}",
                'ganancia_total': f"{r[4]:.2f}",
                'margen_pct': r[5],
            }
            for r in cur.fetchall()
        ]

        # Cuántos productos activos no tienen precio de compra
        cur.execute("""
            SELECT COUNT(*)
            FROM producto_variante
            WHERE id_negocio = %s
              AND activo = TRUE
              AND precio_compra IS NULL
        """, (current_user.id_negocio,))
        sin_costo = cur.fetchone()[0]

    return render_template('productos_mas_vendidos.html',
                           top_rentables=top_rentables,
                           menos_rentables=menos_rentables,
                           sin_costo=sin_costo)


# --------- ENDPOINT API PARA PRECIOS ---------------

@app.route('/api/precios_productos')
@login_required
def api_precios_productos():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT id, precio FROM producto_variante
        WHERE id_negocio = %s
    """, (current_user.id_negocio,))
    precios = {str(row[0]): float(row[1]) for row in cur.fetchall()}
    
    cur.close()
    conn.close()
    
    from flask import jsonify
    return jsonify(precios)



# ============ APIs para filtros de vehículos ============

@app.route('/api/marcas_vehiculo')
@login_required
def api_marcas_vehiculo():
    """Devuelve todas las marcas de vehículos únicas"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT DISTINCT marca 
        FROM vehiculo
        WHERE id_negocio = %s
        ORDER BY marca
    """, (current_user.id_negocio,))
    
    marcas = [row[0] for row in cur.fetchall()]
    
    cur.close()
    conn.close()
    
    return jsonify(marcas)


@app.route('/api/modelos_vehiculo/<marca>')
@login_required
def api_modelos_vehiculo(marca):
    """Devuelve los modelos de una marca específica"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT DISTINCT modelo 
        FROM vehiculo 
        WHERE marca = %s
        AND id_negocio = %s
        ORDER BY modelo
    """, (marca, current_user.id_negocio))
    
    modelos = [row[0] for row in cur.fetchall()]
    
    cur.close()
    conn.close()
    
    return jsonify(modelos)


@app.route('/api/motores_vehiculo/<marca>/<modelo>')
@login_required
def api_motores_vehiculo(marca, modelo):
    """Devuelve los motores de una marca y modelo específicos"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT DISTINCT motor 
        FROM vehiculo 
        WHERE marca = %s AND modelo = %s
        AND id_negocio = %s
        ORDER BY motor
    """, (marca, modelo, current_user.id_negocio))
    
    motores = [row[0] if row[0] else 'Sin motor especificado' for row in cur.fetchall()]
    
    cur.close()
    conn.close()
    
    return jsonify(motores)


@app.route('/api/productos_por_vehiculo')
@login_required
def api_productos_por_vehiculo():
    """Devuelve IDs de productos variantes compatibles con un vehículo específico"""
    marca = request.args.get('marca')
    modelo = request.args.get('modelo', None)
    motor = request.args.get('motor', None)
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Construir query dinámicamente
    query = """
        SELECT DISTINCT pv.id
        FROM producto_variante pv
        JOIN producto_vehiculo pve ON pve.id_producto_variante = pv.id_producto_base
        JOIN vehiculo v ON v.id = pve.id_vehiculo
        WHERE v.marca = %s
        AND pv.id_negocio = %s
    """
    
    params = [marca, current_user.id_negocio]
    
    # Si hay modelo, agregarlo al filtro
    if modelo:
        query += " AND v.modelo = %s"
        params.append(modelo)
    
    # Si hay motor, agregarlo al filtro
    if motor:
        if motor == 'Sin motor especificado':
            query += " AND v.motor IS NULL"
        else:
            query += " AND v.motor = %s"
            params.append(motor)
    
    cur.execute(query, params)
    
    ids = [row[0] for row in cur.fetchall()]
    
    cur.close()
    conn.close()
    
    return jsonify(ids)


# =============== EDITAR PRODUCTO VARIANTE ===============

@app.route('/editar_variante/<int:id_variante>', methods=['GET', 'POST'])
@login_required
def editar_variante(id_variante):
    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        form_type = request.form.get('form_type', 'editar')
        
        # ===== FORMULARIO DE AJUSTE DE STOCK =====
        if form_type == 'ajustar_stock':
            tipo_ajuste = request.form.get('tipo_ajuste')
            cantidad_ajuste = request.form.get('cantidad_ajuste')
            motivo_ajuste = request.form.get('motivo_ajuste')
            
            mensaje_exito = None
            mensaje_error = None
            
            if tipo_ajuste and cantidad_ajuste:
                try:
                    cur.execute("""
                        SELECT stock, precio_compra, precio 
                        FROM producto_variante 
                        WHERE id = %s AND id_negocio = %s
                    """, (id_variante, current_user.id_negocio))
                    row = cur.fetchone()
                    stock_actual = row[0]
                    precio_compra_actual = row[1]
                    precio_venta_actual = row[2]
                    
                    cantidad_ajuste = int(cantidad_ajuste)
                    
                    if tipo_ajuste == 'positivo':
                        nuevo_stock = stock_actual + cantidad_ajuste
                        tipo_movimiento = 'ajuste_positivo'
                    elif tipo_ajuste == 'negativo':
                        nuevo_stock = max(0, stock_actual - cantidad_ajuste)
                        tipo_movimiento = 'ajuste_negativo'
                    
                    cur.execute("""
                        UPDATE producto_variante 
                        SET stock = %s 
                        WHERE id = %s AND id_negocio = %s
                    """, (nuevo_stock, id_variante, current_user.id_negocio))
                    
                    registrar_movimiento_stock(
                        cur,
                        id_variante,
                        tipo_movimiento,
                        cantidad_ajuste,
                        stock_actual,
                        nuevo_stock,
                        motivo_ajuste or 'Ajuste manual',
                        current_user.id,
                        precio_compra=precio_compra_actual,
                        precio_venta=precio_venta_actual
                    )
                    
                    conn.commit()
                    mensaje_exito = '¡Stock ajustado correctamente!'
                    
                except Exception as e:
                    conn.rollback()
                    mensaje_error = f'Error al ajustar stock: {e}'
        
        # ===== FORMULARIO DE EDITAR PRODUCTO =====
        else:
            if not current_user.es_admin():
                flash('No tenés permisos para editar productos.', 'error')
                return redirect(url_for('listar_productos'))
            
            mensaje_exito = None
            mensaje_error = None
            imagen_url = None
            
            marca = normalizar_texto(request.form['marca'])
            calidad = request.form['calidad'] or None
            precio = request.form['precio']
            precio_compra = request.form['precio_compra'] or None
            stock_minimo = request.form['stock_minimo'] or 5
            ubicacion = request.form['ubicacion'] or None
            
            imagen = request.files.get('imagen')
            if imagen and imagen.filename:
                es_valida, resultado = validar_imagen(imagen)
                
                if not es_valida:
                    flash(resultado, 'error')
                    return redirect(url_for('editar_variante', id_variante=id_variante))
                
                imagen_bytes = resultado

                try:
                    import uuid
                    supabase = get_supabase_client()
                    extension = imagen.filename.rsplit('.', 1)[-1].lower()
                    nombre_archivo = f"variante_{id_variante}_{uuid.uuid4().hex}.{extension}"

                    supabase.storage.from_('productos').upload(
                        nombre_archivo,
                        imagen_bytes,
                        {"content-type": f"image/{extension}"}
                    )
                    imagen_url = supabase.storage.from_('productos').get_public_url(nombre_archivo)
                except Exception as e:
                    logger.error("Error al subir imagen en editar_variante: %s", type(e).__name__)
                    imagen_url = None
            
            try:
                ids_proveedores = request.form.getlist('proveedores')
                
                cur.execute("""
                    DELETE FROM producto_proveedor WHERE id_producto_variante = %s
                """, (id_variante,))
                
                for id_prov in ids_proveedores:
                    cur.execute("""
                        INSERT INTO producto_proveedor (id_producto_variante, id_proveedor)
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING
                    """, (id_variante, id_prov))
                
                if imagen_url:
                    cur.execute("""
                        UPDATE producto_variante
                        SET marca = %s,
                            calidad = %s,
                            precio = %s,
                            precio_compra = %s,
                            stock_minimo = %s,
                            ubicacion = %s,
                            imagen_url = %s
                        WHERE id = %s AND id_negocio = %s
                    """, (marca, calidad, precio, precio_compra,
                          stock_minimo, ubicacion, imagen_url, 
                          id_variante, current_user.id_negocio))
                else:
                    cur.execute("""
                        UPDATE producto_variante
                        SET marca = %s, calidad = %s, precio = %s,
                            precio_compra = %s, stock_minimo = %s,
                            ubicacion = %s
                        WHERE id = %s AND id_negocio = %s
                    """, (marca, calidad, precio, precio_compra,
                        stock_minimo, ubicacion, 
                        id_variante, current_user.id_negocio))
                
                conn.commit()
                mensaje_exito = '¡Producto actualizado correctamente!'
                
            except Exception as e:
                conn.rollback()
                mensaje_error = f'Error al actualizar: {e}'
        
        # ===== RECARGAR DATOS DESPUÉS DE CUALQUIER OPERACIÓN =====
        cur.execute("""
            SELECT
                pv.id,
                pb.nombre AS producto_base,
                pv.marca,
                pv.calidad,
                pv.precio,
                pv.precio_compra,
                pv.stock,
                pv.stock_minimo,
                pv.ubicacion,
                pv.imagen_url
            FROM producto_variante pv
            JOIN producto_base pb ON pb.id = pv.id_producto_base
            WHERE pv.id = %s AND pv.id_negocio = %s
        """, (id_variante, current_user.id_negocio))
        
        v = cur.fetchone()
        variante = {
            "id": v[0],
            "producto_base": v[1],
            "marca": v[2],
            "calidad": v[3],
            "precio": v[4],
            "precio_compra": v[5],
            "stock": v[6],
            "stock_minimo": v[7],
            "ubicacion": v[8],
            "imagen_url": v[9]
        }
        
        cur.execute("""
            SELECT id, nombre FROM proveedor 
            WHERE id_negocio = %s
            ORDER BY nombre
        """, (current_user.id_negocio,))
        proveedores = cur.fetchall()
        
        cur.execute("""
            SELECT id_proveedor 
            FROM producto_proveedor 
            WHERE id_producto_variante = %s
        """, (id_variante,))
        variante['proveedores_ids'] = [row[0] for row in cur.fetchall()]
        
        cur.execute("""
            SELECT
                TO_CHAR(m.fecha, 'DD/MM/YYYY HH24:MI') as fecha,
                m.tipo,
                m.cantidad,
                m.stock_antes,
                m.stock_despues,
                m.motivo,
                u.nombre as usuario,
                m.precio_compra,
                m.precio_venta
            FROM movimiento_stock m
            LEFT JOIN usuario u ON u.id = m.id_usuario
            WHERE m.id_producto_variante = %s
            ORDER BY m.fecha DESC
            LIMIT 50
        """, (id_variante,))
        
        movimientos = []
        for r in cur.fetchall():
            movimientos.append({
                "fecha": r[0],
                "tipo": r[1],
                "cantidad": r[2],
                "stock_antes": r[3],
                "stock_despues": r[4],
                "motivo": r[5],
                "usuario": r[6],
                "precio_compra": f"{r[7]:.2f}" if r[7] else None,
                "precio_venta": f"{r[8]:.2f}" if r[8] else None
            })
        
        cur.close()
        conn.close()
        
        return render_template('editar_variante.html',
                             variante=variante,
                             proveedores=proveedores,
                             movimientos=movimientos,
                             mensaje_exito=mensaje_exito,
                             mensaje_error=mensaje_error)
    
    # ===== GET: CARGAR DATOS DEL PRODUCTO =====
    cur.execute("""
        SELECT
            pv.id,
            pb.nombre AS producto_base,
            pv.marca,
            pv.calidad,
            pv.precio,
            pv.precio_compra,
            pv.stock,
            pv.stock_minimo,
            pv.ubicacion,
            pv.imagen_url
        FROM producto_variante pv
        JOIN producto_base pb ON pb.id = pv.id_producto_base
        WHERE pv.id = %s AND pv.id_negocio = %s
    """, (id_variante, current_user.id_negocio))
    
    v = cur.fetchone()
    
    if not v:
        return render_template('404.html',
                            mensaje=f'El producto #{id_variante} no existe.'), 404
    
    variante = {
        "id": v[0],
        "producto_base": v[1],
        "marca": v[2],
        "calidad": v[3],
        "precio": v[4],
        "precio_compra": v[5],
        "stock": v[6],
        "stock_minimo": v[7],
        "ubicacion": v[8],
        "imagen_url": v[9]
    }
    
    cur.execute("""
        SELECT id, nombre FROM proveedor 
        WHERE id_negocio = %s
        ORDER BY nombre
    """, (current_user.id_negocio,))
    proveedores = cur.fetchall()
    
    cur.execute("""
        SELECT id_proveedor 
        FROM producto_proveedor 
        WHERE id_producto_variante = %s
    """, (id_variante,))
    variante['proveedores_ids'] = [row[0] for row in cur.fetchall()]
    
    cur.execute("""
        SELECT
            TO_CHAR(m.fecha, 'DD/MM/YYYY HH24:MI') as fecha,
            m.tipo,
            m.cantidad,
            m.stock_antes,
            m.stock_despues,
            m.motivo,
            u.nombre as usuario,
            m.precio_compra,
            m.precio_venta
        FROM movimiento_stock m
        LEFT JOIN usuario u ON u.id = m.id_usuario
        WHERE m.id_producto_variante = %s
        ORDER BY m.fecha DESC
        LIMIT 50
    """, (id_variante,))
    
    movimientos = []
    for r in cur.fetchall():
        movimientos.append({
            "fecha": r[0],
            "tipo": r[1],
            "cantidad": r[2],
            "stock_antes": r[3],
            "stock_despues": r[4],
            "motivo": r[5],
            "usuario": r[6],
            "precio_compra": f"{r[7]:.2f}" if r[7] else None,
            "precio_venta": f"{r[8]:.2f}" if r[8] else None
        })
    
    cur.close()
    conn.close()
    
    return render_template('editar_variante.html',
                         variante=variante,
                         proveedores=proveedores,
                         movimientos=movimientos)



# ============ GESTIÓN DE USUARIOS (solo admin) ============

def solo_admin(f):
    """Decorador que permite acceso solo a admins"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.es_admin():
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/usuarios')
@login_required
@solo_admin
def listar_usuarios():
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT id, nombre, email, rol, activo,
                TO_CHAR(creado_en, 'DD/MM/YYYY')
            FROM usuario 
            WHERE id_negocio = %s
            ORDER BY creado_en DESC
        """, (current_user.id_negocio,))
        usuarios = [{'id': u[0], 'nombre': u[1], 'email': u[2],
                     'rol': u[3], 'activo': u[4], 'creado_en': u[5]}
                    for u in cur.fetchall()]
    return render_template('usuarios.html', usuarios=usuarios)


@app.route('/usuarios/crear', methods=['POST'])
@login_required
@solo_admin
def crear_usuario():
    nombre = request.form['nombre']
    email = request.form['email']
    password = request.form['password']
    rol = request.form['rol']

    if len(password) < 8:
        flash('La contraseña debe tener al menos 8 caracteres.', 'error')
        return redirect(url_for('listar_usuarios'))

    try:
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        with get_db() as (conn, cur):
            cur.execute("""
                INSERT INTO usuario (nombre, email, password_hash, rol, activo, id_negocio)
                VALUES (%s, %s, %s, %s, TRUE, %s)
            """, (nombre, email, password_hash, rol, current_user.id_negocio))
            conn.commit()
        flash(f'Usuario "{nombre}" creado correctamente.', 'success')
    except Exception as e:
        if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
            flash(f'El email "{email}" ya está registrado.', 'error')
        else:
            flash(f'Error al crear usuario: {str(e)}', 'error')
    return redirect(url_for('listar_usuarios'))

@app.route('/usuarios/desactivar/<int:id_usuario>')
@login_required
@solo_admin
def desactivar_usuario(id_usuario):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        UPDATE usuario SET activo = FALSE WHERE id = %s
    """, (id_usuario,))
    
    conn.commit()
    cur.close()
    conn.close()
    
    return redirect(url_for('listar_usuarios'))


@app.route('/usuarios/activar/<int:id_usuario>')
@login_required
@solo_admin
def activar_usuario(id_usuario):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        UPDATE usuario SET activo = TRUE WHERE id = %s
    """, (id_usuario,))
    
    conn.commit()
    cur.close()
    conn.close()
    
    return redirect(url_for('listar_usuarios'))


@app.route('/usuarios/toggle_activo/<int:id_usuario>')
@login_required
@solo_admin
def toggle_usuario_activo(id_usuario):
    try:
        with get_db() as (conn, cur):
            cur.execute("""
                SELECT nombre, activo FROM usuario 
                WHERE id = %s AND id_negocio = %s
            """, (id_usuario, current_user.id_negocio))
            usuario = cur.fetchone()
            if not usuario:
                flash('Usuario no encontrado.', 'error')
                return redirect(url_for('listar_usuarios'))
            nuevo_estado = not usuario[1]
            cur.execute("""
                UPDATE usuario SET activo = %s 
                WHERE id = %s AND id_negocio = %s
            """, (nuevo_estado, id_usuario, current_user.id_negocio))
            conn.commit()
        flash(f'Usuario "{usuario[0]}" {"activado" if nuevo_estado else "desactivado"}.', 
              'success' if nuevo_estado else 'warning')
    except Exception as e:
        flash(f'Error al cambiar estado: {str(e)}', 'error')
    return redirect(url_for('listar_usuarios'))

# ============ REPORTES ============

@app.route('/reportes')
@login_required
@solo_admin
def reportes():
    conn = get_db_connection()
    cur = conn.cursor()
    id_negocio = current_user.id_negocio

    # ===========================================================================
    # HELPERS INTERNOS
    # ===========================================================================

    def fetch_ingreso_periodo(cur, id_negocio, desde=None, hasta=None, truncar_mes=False):
        """
        Devuelve (total_ingresos, cantidad_operaciones) para un período dado.
        Ingreso real = ventas contado cobradas + pagos de cuenta corriente.
        Las ventas a cuenta corriente NO se cuentan hasta que se cobran.
        """
        # --- Ventas contado ---
        cond_v = [
            "id_negocio = %s",
            "tipo_pago = 'contado'",
            "anulada = FALSE",
        ]
        params_v = [id_negocio]

        if truncar_mes:
            cond_v.append("DATE_TRUNC('month', fecha) = DATE_TRUNC('month', CURRENT_DATE)")
        if desde:
            cond_v.append("DATE(fecha) >= %s")
            params_v.append(desde)
        if hasta:
            cond_v.append("DATE(fecha) <= %s")
            params_v.append(hasta)

        cur.execute(f"""
            SELECT COALESCE(SUM(total), 0), COUNT(*)
            FROM venta
            WHERE {" AND ".join(cond_v)}
        """, params_v)
        total_v, cant_v = cur.fetchone()

        # --- Pagos de cuenta corriente ---
        cond_mc = [
            "id_negocio = %s",
            "tipo = 'pago'",
        ]
        params_mc = [id_negocio]

        if truncar_mes:
            cond_mc.append("DATE_TRUNC('month', fecha) = DATE_TRUNC('month', CURRENT_DATE)")
        if desde:
            cond_mc.append("DATE(fecha) >= %s")
            params_mc.append(desde)
        if hasta:
            cond_mc.append("DATE(fecha) <= %s")
            params_mc.append(hasta)

        cur.execute(f"""
            SELECT COALESCE(SUM(monto), 0), COUNT(*)
            FROM movimiento_cuenta
            WHERE {" AND ".join(cond_mc)}
        """, params_mc)
        total_mc, cant_mc = cur.fetchone()

        return float(total_v) + float(total_mc), int(cant_v) + int(cant_mc)


    def fetch_ganancia_periodo(cur, id_negocio, desde=None, hasta=None, truncar_mes=False):
        cond = [
            "v.id_negocio = %s",
            "v.tipo_pago = 'contado'",
            "v.anulada = FALSE",
            "vd.precio_compra IS NOT NULL",  # ← excluye productos sin costo
        ]
        params = [id_negocio]

        if truncar_mes:
            cond.append("DATE_TRUNC('month', v.fecha) = DATE_TRUNC('month', CURRENT_DATE)")
        if desde:
            cond.append("DATE(v.fecha) >= %s")
            params.append(desde)
        if hasta:
            cond.append("DATE(v.fecha) <= %s")
            params.append(hasta)

        cur.execute(f"""
            SELECT COALESCE(SUM(
                vd.cantidad * (vd.precio_unitario - vd.precio_compra)
            ), 0)
            FROM venta_detalle vd
            JOIN venta v ON v.id = vd.id_venta
            WHERE {" AND ".join(cond)}
        """, params)
        return float(cur.fetchone()[0])


    def fetch_productos_sin_costo(cur, id_negocio):
        cur.execute("""
            SELECT COUNT(DISTINCT pv.id)
            FROM producto_variante pv
            WHERE pv.id_negocio = %s
            AND pv.precio_compra IS NULL
            AND pv.activo = TRUE
        """, (id_negocio,))
        return int(cur.fetchone()[0])


    # ===========================================================================
    # RESUMEN RÁPIDO
    # ===========================================================================

    # Hoy
    cur.execute("""
        SELECT COALESCE(SUM(total), 0), COUNT(*)
        FROM venta
        WHERE DATE(fecha) = CURRENT_DATE
          AND id_negocio = %s
          AND tipo_pago = 'contado'
          AND anulada = FALSE
    """, (id_negocio,))
    r = cur.fetchone()
    cur.execute("""
        SELECT COALESCE(SUM(monto), 0), COUNT(*)
        FROM movimiento_cuenta
        WHERE DATE(fecha) = CURRENT_DATE
          AND id_negocio = %s
          AND tipo = 'pago'
    """, (id_negocio,))
    r_cc = cur.fetchone()
    hoy = {
        "total": f"{float(r[0]) + float(r_cc[0]):.2f}",
        "cantidad": int(r[1]) + int(r_cc[1])
    }

    # Esta semana
    cur.execute("""
        SELECT COALESCE(SUM(total), 0), COUNT(*)
        FROM venta
        WHERE DATE(fecha) >= DATE_TRUNC('week', CURRENT_DATE)
          AND id_negocio = %s
          AND tipo_pago = 'contado'
          AND anulada = FALSE
    """, (id_negocio,))
    r = cur.fetchone()
    cur.execute("""
        SELECT COALESCE(SUM(monto), 0), COUNT(*)
        FROM movimiento_cuenta
        WHERE DATE(fecha) >= DATE_TRUNC('week', CURRENT_DATE)
          AND id_negocio = %s
          AND tipo = 'pago'
    """, (id_negocio,))
    r_cc = cur.fetchone()
    semana = {
        "total": f"{float(r[0]) + float(r_cc[0]):.2f}",
        "cantidad": int(r[1]) + int(r_cc[1])
    }

    # Este mes
    cur.execute("""
        SELECT COALESCE(SUM(total), 0), COUNT(*)
        FROM venta
        WHERE DATE_TRUNC('month', fecha) = DATE_TRUNC('month', CURRENT_DATE)
          AND id_negocio = %s
          AND tipo_pago = 'contado'
          AND anulada = FALSE
    """, (id_negocio,))
    r = cur.fetchone()
    cur.execute("""
        SELECT COALESCE(SUM(monto), 0), COUNT(*)
        FROM movimiento_cuenta
        WHERE DATE_TRUNC('month', fecha) = DATE_TRUNC('month', CURRENT_DATE)
          AND id_negocio = %s
          AND tipo = 'pago'
    """, (id_negocio,))
    r_cc = cur.fetchone()
    mes = {
        "total": f"{float(r[0]) + float(r_cc[0]):.2f}",
        "cantidad": int(r[1]) + int(r_cc[1])
    }

    # Ganancia real del mes (solo ventas contado)
    ganancia_mes = f"{fetch_ganancia_periodo(cur, id_negocio, truncar_mes=True):.2f}"
    productos_sin_costo = fetch_productos_sin_costo(cur, id_negocio) 

    resumen = {
        "hoy": hoy,
        "semana": semana,
        "mes": mes,
        "ganancia_mes": ganancia_mes
    }

    # ===========================================================================
    # FILTRO POR PERÍODO
    # ===========================================================================
    desde = request.args.get('desde')
    hasta = request.args.get('hasta')
    filtro = {"desde": desde, "hasta": hasta}

    periodo = None
    ventas_por_dia = []

    if desde or hasta:
        # --- Total ingresos del período ---
        cond_v = ["v.id_negocio = %s", "v.tipo_pago = 'contado'", "v.anulada = FALSE"]
        params_v = [id_negocio]
        cond_mc = ["mc.id_negocio = %s", "mc.tipo = 'pago'"]
        params_mc = [id_negocio]

        if desde:
            cond_v.append("DATE(v.fecha) >= %s");  params_v.append(desde)
            cond_mc.append("DATE(mc.fecha) >= %s"); params_mc.append(desde)
        if hasta:
            cond_v.append("DATE(v.fecha) <= %s");  params_v.append(hasta)
            cond_mc.append("DATE(mc.fecha) <= %s"); params_mc.append(hasta)

        where_v  = " AND ".join(cond_v)
        where_mc = " AND ".join(cond_mc)

        cur.execute(f"""
            SELECT COALESCE(SUM(total), 0), COUNT(*)
            FROM venta v
            WHERE {where_v}
        """, params_v)
        r = cur.fetchone()
        total_contado   = float(r[0])
        cantidad_contado = int(r[1])

        cur.execute(f"""
            SELECT COALESCE(SUM(monto), 0), COUNT(*)
            FROM movimiento_cuenta mc
            WHERE {where_mc}
        """, params_mc)
        r = cur.fetchone()
        total_cc   = float(r[0])
        cantidad_cc = int(r[1])

        total_periodo    = total_contado + total_cc
        cantidad_periodo = cantidad_contado + cantidad_cc
        ganancia_periodo = fetch_ganancia_periodo(cur, id_negocio, desde=desde, hasta=hasta)
        promedio = total_periodo / cantidad_periodo if cantidad_periodo > 0 else 0

        periodo = {
            "total":    f"{total_periodo:.2f}",
            "cantidad": cantidad_periodo,
            "ganancia": f"{ganancia_periodo:.2f}",
            "promedio": f"{promedio:.2f}"
        }

    # ===========================================================================
    # VENTAS POR DÍA
    # ===========================================================================
    if desde or hasta:
        cond_dia_v  = ["v.id_negocio = %s", "v.tipo_pago = 'contado'", "v.anulada = FALSE"]
        params_dia_v = [id_negocio]
        cond_dia_mc  = ["mc.id_negocio = %s", "mc.tipo = 'pago'"]
        params_dia_mc = [id_negocio]

        if desde:
            cond_dia_v.append("DATE(v.fecha) >= %s");   params_dia_v.append(desde)
            cond_dia_mc.append("DATE(mc.fecha) >= %s"); params_dia_mc.append(desde)
        if hasta:
            cond_dia_v.append("DATE(v.fecha) <= %s");   params_dia_v.append(hasta)
            cond_dia_mc.append("DATE(mc.fecha) <= %s"); params_dia_mc.append(hasta)

        where_dia_v  = " AND ".join(cond_dia_v)
        where_dia_mc = " AND ".join(cond_dia_mc)
    else:
        where_dia_v  = "v.id_negocio = %s AND v.tipo_pago = 'contado' AND v.anulada = FALSE AND DATE(v.fecha) >= CURRENT_DATE - INTERVAL '30 days'"
        params_dia_v  = [id_negocio]
        where_dia_mc = "mc.id_negocio = %s AND mc.tipo = 'pago' AND DATE(mc.fecha) >= CURRENT_DATE - INTERVAL '30 days'"
        params_dia_mc = [id_negocio]

    # Ingresos por día: ventas contado
    cur.execute(f"""
        SELECT
            DATE(v.fecha)                                                          AS dia,
            COUNT(DISTINCT v.id)                                                   AS cantidad,
            COALESCE(SUM(v.total), 0)                                              AS total,
            COALESCE(SUM(
                CASE WHEN vd.precio_compra IS NOT NULL
                    THEN vd.cantidad * (vd.precio_unitario - vd.precio_compra)
                    ELSE 0
                END
            ), 0)                                                                   AS ganancia
        FROM venta v
        LEFT JOIN venta_detalle vd ON vd.id_venta = v.id
        WHERE {where_dia_v}
        GROUP BY DATE(v.fecha)
    """, params_dia_v)
    dias_contado = {r[0]: {"cantidad": r[1], "total": float(r[2]), "ganancia": float(r[3])}
                    for r in cur.fetchall()}

    # Ingresos por día: pagos CC
    cur.execute(f"""
        SELECT
            DATE(mc.fecha)             AS dia,
            COUNT(*)                   AS cantidad,
            COALESCE(SUM(mc.monto), 0) AS total
        FROM movimiento_cuenta mc
        WHERE {where_dia_mc}
        GROUP BY DATE(mc.fecha)
    """, params_dia_mc)
    dias_cc = {r[0]: {"cantidad": r[1], "total": float(r[2])} for r in cur.fetchall()}

    # Combinar ambos por día
    todos_dias = set(dias_contado.keys()) | set(dias_cc.keys())
    for dia in sorted(todos_dias, reverse=True):
        c = dias_contado.get(dia, {"cantidad": 0, "total": 0.0, "ganancia": 0.0})
        p = dias_cc.get(dia, {"cantidad": 0, "total": 0.0})
        ventas_por_dia.append({
            "fecha":    dia.strftime("%d/%m/%Y"),
            "cantidad": c["cantidad"] + p["cantidad"],
            "total":    f"{c['total'] + p['total']:.2f}",
            "ganancia": f"{c['ganancia']:.2f}",   # ganancia solo en contado
        })

    # ===========================================================================
    # HISTORIAL POR MES (últimos 12 meses)
    # Combina ventas contado + pagos CC agrupados por mes
    # ===========================================================================

    # Contado por mes
    cur.execute("""
        SELECT
            DATE_TRUNC('month', v.fecha)                                           AS mes_dt,
            COUNT(DISTINCT v.id)                                                   AS cantidad,
            COALESCE(SUM(v.total), 0)                                              AS total,
            COALESCE(SUM(
                CASE WHEN vd.precio_compra IS NOT NULL
                    THEN vd.cantidad * (vd.precio_unitario - vd.precio_compra)
                    ELSE 0
                END
            ), 0)                                                                   AS ganancia
        FROM venta v
        LEFT JOIN venta_detalle vd ON vd.id_venta = v.id
        WHERE v.fecha >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '11 months'
        AND v.id_negocio = %s
        AND v.tipo_pago = 'contado'
        AND v.anulada = FALSE
        GROUP BY DATE_TRUNC('month', v.fecha)
    """, (id_negocio,))
    meses_contado = {r[0]: {"cantidad": int(r[1]), "total": float(r[2]), "ganancia": float(r[3])}
                     for r in cur.fetchall()}

    # Pagos CC por mes
    cur.execute("""
        SELECT
            DATE_TRUNC('month', mc.fecha) AS mes_dt,
            COUNT(*)                       AS cantidad,
            COALESCE(SUM(mc.monto), 0)     AS total
        FROM movimiento_cuenta mc
        WHERE mc.fecha >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '11 months'
          AND mc.id_negocio = %s
          AND mc.tipo = 'pago'
        GROUP BY DATE_TRUNC('month', mc.fecha)
    """, (id_negocio,))
    meses_cc = {r[0]: {"cantidad": int(r[1]), "total": float(r[2])}
                for r in cur.fetchall()}

    todos_meses = set(meses_contado.keys()) | set(meses_cc.keys())
    historial_meses = []
    for mes_dt in sorted(todos_meses, reverse=True):
        c = meses_contado.get(mes_dt, {"cantidad": 0, "total": 0.0, "ganancia": 0.0})
        p = meses_cc.get(mes_dt, {"cantidad": 0, "total": 0.0})
        historial_meses.append({
            "mes":              mes_dt.strftime("%B %Y").capitalize(),
            "cantidad_ventas":  c["cantidad"] + p["cantidad"],
            "total_facturado":  f"{c['total'] + p['total']:.2f}",
            "ganancia_real":    f"{c['ganancia']:.2f}",
        })

    # ===========================================================================
    # MÉTODOS DE PAGO
    # Solo ventas CONTADO + pagos CC (nunca ventas CC sin cobrar)
    # ===========================================================================
    cur2 = conn.cursor()

    if desde or hasta:
        cond_mp = ["v.id_negocio = %s", "v.anulada = FALSE", "v.tipo_pago = 'contado'"]
        params_mp = [id_negocio]
        if desde:
            cond_mp.append("DATE(v.fecha) >= %s"); params_mp.append(desde)
        if hasta:
            cond_mp.append("DATE(v.fecha) <= %s"); params_mp.append(hasta)

        cond_mc2 = ["mc.id_negocio = %s", "mc.tipo = 'pago'"]
        params_mc2 = [id_negocio]
        if desde:
            cond_mc2.append("DATE(mc.fecha) >= %s"); params_mc2.append(desde)
        if hasta:
            cond_mc2.append("DATE(mc.fecha) <= %s"); params_mc2.append(hasta)
    else:
        cond_mp = [
            "v.id_negocio = %s", "v.anulada = FALSE", "v.tipo_pago = 'contado'",
            "DATE_TRUNC('month', v.fecha) = DATE_TRUNC('month', CURRENT_DATE)"
        ]
        params_mp = [id_negocio]

        cond_mc2 = [
            "mc.id_negocio = %s", "mc.tipo = 'pago'",
            "DATE_TRUNC('month', mc.fecha) = DATE_TRUNC('month', CURRENT_DATE)"
        ]
        params_mc2 = [id_negocio]

    where_mp  = " AND ".join(cond_mp)
    where_mc2 = " AND ".join(cond_mc2)

    cur2.execute(f"""
        SELECT COALESCE(metodo_pago, 'efectivo'), COUNT(*), COALESCE(SUM(total), 0)
        FROM venta v
        WHERE {where_mp}
        GROUP BY metodo_pago
        ORDER BY 3 DESC
    """, params_mp)
    ventas_rows = cur2.fetchall()

    cur2.execute(f"""
        SELECT COALESCE(mc.metodo_pago, 'efectivo'), COUNT(*), COALESCE(SUM(mc.monto), 0)
        FROM movimiento_cuenta mc
        WHERE {where_mc2}
        GROUP BY mc.metodo_pago
    """, params_mc2)
    cc_rows = cur2.fetchall()

    from collections import defaultdict
    totales = defaultdict(lambda: {'cantidad': 0, 'total': 0.0})
    for r in ventas_rows:
        totales[r[0]]['cantidad'] += r[1]
        totales[r[0]]['total']    += float(r[2])
    for r in cc_rows:
        totales[r[0]]['cantidad'] += r[1]
        totales[r[0]]['total']    += float(r[2])

    metodos_pago_mes = [
        {'metodo': metodo, 'cantidad': v['cantidad'], 'total': f"{v['total']:.2f}"}
        for metodo, v in sorted(totales.items(), key=lambda x: x[1]['total'], reverse=True)
    ]

    # ===========================================================================
    # COBROS DETALLADOS (tabla de movimientos visibles)
    # Muestra ventas contado + pagos CC — nunca ventas CC sin cobrar
    # ===========================================================================

    # Ventas contado del período
    cur2.execute(f"""
        SELECT
            TO_CHAR(v.fecha, 'DD/MM/YYYY HH24:MI'),
            COALESCE(c.nombre, 'Mostrador'),
            COALESCE(v.metodo_pago, 'efectivo'),
            v.total,
            'venta_contado' AS origen
        FROM venta v
        LEFT JOIN cliente c ON c.id = v.id_cliente
        WHERE {where_mp}
        ORDER BY v.fecha DESC
    """, params_mp)
    ventas_cobros_contado = [
        {'fecha': r[0], 'cliente': r[1], 'metodo_pago': r[2],
         'total': f"{r[3]:.2f}", 'origen': r[4]}
        for r in cur2.fetchall()
    ]

    # Pagos CC del período
    cur2.execute(f"""
        SELECT
            TO_CHAR(mc.fecha, 'DD/MM/YYYY HH24:MI'),
            COALESCE(c.nombre, 'Cliente'),
            COALESCE(mc.metodo_pago, 'efectivo'),
            mc.monto,
            'pago_cc' AS origen
        FROM movimiento_cuenta mc
        LEFT JOIN cliente c ON c.id = mc.id_cliente
        WHERE {where_mc2}
        ORDER BY mc.fecha DESC
    """, params_mc2)
    ventas_cobros_cc = [
        {'fecha': r[0], 'cliente': r[1], 'metodo_pago': r[2],
         'total': f"{r[3]:.2f}", 'origen': r[4]}
        for r in cur2.fetchall()
    ]

    # Combinar y ordenar por fecha desc
    ventas_cobros = sorted(
        ventas_cobros_contado + ventas_cobros_cc,
        key=lambda x: x['fecha'],
        reverse=True
    )

    cur2.close()
    cur.close()
    conn.close()

    return render_template('reportes.html',
                           resumen=resumen,
                           productos_sin_costo=productos_sin_costo,
                           filtro=filtro,
                           periodo=periodo,
                           ventas_por_dia=ventas_por_dia,
                           historial_meses=historial_meses,
                           metodos_pago_mes=metodos_pago_mes,
                           ventas_cobros=ventas_cobros)



# ============ MOVIMIENTOS DE STOCK ============

@app.route('/movimientos_stock')
@login_required
def movimientos_stock():
    tipo = request.args.get('tipo', '')
    producto = request.args.get('producto', '')
    desde = request.args.get('desde', '')
    hasta = request.args.get('hasta', '')
    filtro = {'tipo': tipo, 'producto': producto, 'desde': desde, 'hasta': hasta}

    condiciones = ["pv.id_negocio = %s"]
    params = [current_user.id_negocio]
    if tipo:
        condiciones.append("m.tipo = %s")
        params.append(tipo)
    if producto:
        condiciones.append("(LOWER(pb.nombre) LIKE %s OR LOWER(pv.marca) LIKE %s)")
        params.extend([f"%{producto.lower()}%"] * 2)
    if desde:
        condiciones.append("DATE(m.fecha) >= %s")
        params.append(desde)
    if hasta:
        condiciones.append("DATE(m.fecha) <= %s")
        params.append(hasta)

    where = " AND ".join(condiciones) if condiciones else "1=1"

    with get_db() as (conn, cur):
        cur.execute(f"""
            SELECT TO_CHAR(m.fecha, 'DD/MM/YYYY HH24:MI'),
                   pb.nombre, pv.marca, m.tipo, m.cantidad,
                   m.stock_antes, m.stock_despues, m.motivo,
                   u.nombre, m.precio_compra, m.precio_venta
            FROM movimiento_stock m
            JOIN producto_variante pv ON pv.id = m.id_producto_variante
            JOIN producto_base pb ON pb.id = pv.id_producto_base
            LEFT JOIN usuario u ON u.id = m.id_usuario
            WHERE {where}
            ORDER BY m.fecha DESC
            LIMIT 200
        """, params)
        movimientos = [{'fecha': r[0], 'producto': r[1], 'marca': r[2],
                        'tipo': r[3], 'cantidad': r[4], 'stock_antes': r[5],
                        'stock_despues': r[6], 'motivo': r[7], 'usuario': r[8],
                        'precio_compra': f"{r[9]:.2f}" if r[9] else None,
                        'precio_venta': f"{r[10]:.2f}" if r[10] else None}
                       for r in cur.fetchall()]

    return render_template('movimientos_stock.html', movimientos=movimientos, filtro=filtro)


# ============ CUENTAS CORRIENTE ============

@app.route('/cuentas_corriente')
@login_required
def cuentas_corriente():
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT 
                c.id,
                c.nombre,
                c.contacto,
                cc.saldo,
                cc.id AS id_cuenta
            FROM cuenta_corriente cc
            JOIN cliente c ON c.id = cc.id_cliente
            WHERE cc.id_negocio = %s
            AND cc.saldo > 0
            ORDER BY c.nombre
        """, (current_user.id_negocio,))
        
        cuentas = [{
            'id_cuenta': r[4],
            'id_cliente': r[0],
            'cliente': r[1],
            'contacto': r[2] or '-',
            'saldo': f"{r[3]:.2f}"
        } for r in cur.fetchall()]
 
        cur.execute("""
            SELECT 
                mc.fecha,
                c.nombre,
                mc.tipo,
                mc.monto,
                mc.descripcion
            FROM movimiento_cuenta mc
            JOIN cliente c ON c.id = mc.id_cliente
            WHERE mc.id_negocio = %s
            ORDER BY mc.fecha DESC
            LIMIT 50
        """, (current_user.id_negocio,))
 
        movimientos = [{
            'fecha': r[0].strftime("%d/%m/%Y %H:%M"),
            'cliente': r[1],
            'tipo': r[2],
            'monto': f"{r[3]:.2f}",
            'descripcion': r[4] or '-'
        } for r in cur.fetchall()]
 
    return render_template('cuentas_corriente.html',
                         cuentas=cuentas,
                         movimientos=movimientos)
 
 
@app.route('/cuentas_corriente/pagar', methods=['POST'])
@login_required
def registrar_pago_cuenta():
    id_cliente = request.form.get('id_cliente')
    monto = request.form.get('monto')
    descripcion = request.form.get('descripcion', '').strip()
    metodo_pago = request.form.get('metodo_pago', 'efectivo')
 
    if not id_cliente or not monto:
        flash('Faltan datos para registrar el pago.', 'error')
        return redirect(url_for('cuentas_corriente'))
 
    try:
        monto = float(monto)
        if monto <= 0:
            flash('El monto debe ser mayor a cero.', 'error')
            return redirect(url_for('cuentas_corriente'))
    except ValueError:
        flash('El monto ingresado no es válido.', 'error')
        return redirect(url_for('cuentas_corriente'))
 
    try:
        with get_db() as (conn, cur):
            # Verificar que existe la cuenta y tiene saldo suficiente
            cur.execute("""
                SELECT id, saldo FROM cuenta_corriente
                WHERE id_cliente = %s AND id_negocio = %s
            """, (id_cliente, current_user.id_negocio))
            cuenta = cur.fetchone()
 
            if not cuenta:
                flash('No se encontró la cuenta corriente de ese cliente.', 'error')
                return redirect(url_for('cuentas_corriente'))
 
            if monto > cuenta[1]:
                flash(f'El monto ingresado supera el saldo actual (${cuenta[1]:.2f}).', 'error')
                return redirect(url_for('cuentas_corriente'))
 
            # Registrar el pago
            cur.execute("""
                INSERT INTO movimiento_cuenta
                (id_cliente, id_negocio, tipo, monto, descripcion, metodo_pago)
                VALUES (%s, %s, 'pago', %s, %s, %s)
            """, (id_cliente, current_user.id_negocio, monto,
                  descripcion or 'Pago de cuenta corriente', metodo_pago))
 
            # Actualizar el saldo
            cur.execute("""
                UPDATE cuenta_corriente
                SET saldo = saldo - %s
                WHERE id_cliente = %s AND id_negocio = %s
            """, (monto, id_cliente, current_user.id_negocio))
 
            conn.commit()
 
            # Obtener nombre del cliente para el mensaje
            cur.execute("SELECT nombre FROM cliente WHERE id = %s", (id_cliente,))
            nombre = cur.fetchone()[0]
 
        flash(f'Pago de ${monto:.2f} registrado para {nombre}.', 'success')
 
    except Exception as e:
        flash(f'Error al registrar el pago: {str(e)}', 'error')
 
    return redirect(url_for('cuentas_corriente'))


# ============= FIN =============


if __name__ == "__main__":
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host="0.0.0.0", port=5000, debug=debug)
