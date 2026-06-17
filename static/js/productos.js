// Filtros de productos
const buscarProducto = document.getElementById('buscarProducto');
const filtroStockBajo = document.getElementById('filtroStockBajo');
const filtroInactivos = document.getElementById('filtroInactivos');
const filtroSoloPedidos = document.getElementById('filtroSoloPedidos');
const filtroMarca = document.getElementById('filtroMarca');
const filtroModelo = document.getElementById('filtroModelo');
const filtroMotor = document.getElementById('filtroMotor');
const tablaProductos = document.getElementById('tablaProductos');

let productosCompatibles = []; // IDs de productos compatibles con el vehículo seleccionado

// Cargar marcas de vehículos
fetch('/api/marcas_vehiculo')
    .then(r => r.json())
    .then(marcas => {
        marcas.forEach(marca => {
            const option = document.createElement('option');
            option.value = marca;
            option.textContent = marca;
            filtroMarca.appendChild(option);
        });
    })
    .catch(err => console.error('Error al cargar marcas:', err));

// Cuando cambia la marca, cargar modelos
filtroMarca.addEventListener('change', function() {
    const marca = this.value;
    
    // Resetear modelos y motores
    filtroModelo.innerHTML = '<option value="">Todos los modelos</option>';
    filtroMotor.innerHTML = '<option value="">Todos los motores</option>';
    filtroMotor.disabled = true;
    productosCompatibles = [];
    
    if (marca) {
        filtroModelo.disabled = false;
        
        // Cargar modelos de esta marca
        fetch(`/api/modelos_vehiculo/${encodeURIComponent(marca)}`)
            .then(r => r.json())
            .then(modelos => {
                modelos.forEach(modelo => {
                    const option = document.createElement('option');
                    option.value = modelo;
                    option.textContent = modelo;
                    filtroModelo.appendChild(option);
                });
            })
            .catch(err => console.error('Error al cargar modelos:', err));
        
        // Cargar productos de esta marca (sin modelo específico)
        cargarProductosCompatibles();
    } else {
        filtroModelo.disabled = true;
        ocultarInfoFiltro();
    }
    
    aplicarFiltros();
});

// Cuando cambia el modelo, cargar motores
filtroModelo.addEventListener('change', function() {
    const marca = filtroMarca.value;
    const modelo = this.value;
    
    // Resetear motores
    filtroMotor.innerHTML = '<option value="">Todos los motores</option>';
    productosCompatibles = [];
    
    if (marca && modelo) {
        filtroMotor.disabled = false;
        
        // Cargar motores de esta marca/modelo
        fetch(`/api/motores_vehiculo/${encodeURIComponent(marca)}/${encodeURIComponent(modelo)}`)
            .then(r => r.json())
            .then(motores => {
                motores.forEach(motor => {
                    const option = document.createElement('option');
                    option.value = motor;
                    option.textContent = motor;
                    filtroMotor.appendChild(option);
                });
            })
            .catch(err => console.error('Error al cargar motores:', err));
        
        // Cargar productos compatibles con marca + modelo
        cargarProductosCompatibles();
    } else {
        filtroMotor.disabled = true;
    }
    
    aplicarFiltros();
});

// Cuando cambia el motor
filtroMotor.addEventListener('change', function() {
    cargarProductosCompatibles();
    aplicarFiltros();
});

function cargarProductosCompatibles() {
    const marca = filtroMarca.value;
    const modelo = filtroModelo.value;
    const motor = filtroMotor.value;
    
    if (!marca) {
        productosCompatibles = [];
        ocultarInfoFiltro();
        return;
    }
    
    // Construir URL con parámetros
    let url = `/api/productos_por_vehiculo?marca=${encodeURIComponent(marca)}`;
    if (modelo) url += `&modelo=${encodeURIComponent(modelo)}`;
    if (motor) url += `&motor=${encodeURIComponent(motor)}`;
    
    // Mostrar info de qué se está filtrando
    let textoFiltro = marca;
    if (modelo) textoFiltro += ` ${modelo}`;
    if (motor) textoFiltro += ` (${motor})`;
    
    // Mostrar loading
    const infoDiv = document.getElementById('infoFiltroVehiculo');
    const textoDiv = document.getElementById('textoFiltroVehiculo');
    textoDiv.innerHTML = `<span style="color: var(--gray-500);"> Buscando productos compatibles con ${textoFiltro}...</span>`;
    infoDiv.style.display = 'block';
    
    // Cargar productos compatibles desde la API
    fetch(url)
        .then(r => r.json())
        .then(ids => {
            productosCompatibles = ids;
            console.log(`Productos compatibles con ${textoFiltro}:`, ids);
            
            // Mostrar resultado
            if (ids.length > 0) {
                textoDiv.innerHTML = `${textoFiltro} <span style="color: var(--success); margin-left: 8px;">✓ ${ids.length} productos encontrados</span>`;
            } else {
                textoDiv.innerHTML = `${textoFiltro} <span style="color: var(--warning); margin-left: 8px;">⚠️ No hay productos compatibles</span>`;
            }
            
            aplicarFiltros();
        })
        .catch(err => {
            console.error('Error al cargar productos compatibles:', err);
            textoDiv.innerHTML = `<span style="color: var(--danger);">✗ Error al cargar productos. Intentá de nuevo.</span>`;
            productosCompatibles = [];
            aplicarFiltros();
        });
}

function limpiarFiltroVehiculo() {
    filtroMarca.value = '';
    filtroModelo.innerHTML = '<option value="">Primero seleccioná marca</option>';
    filtroModelo.disabled = true;
    filtroMotor.innerHTML = '<option value="">Primero seleccioná modelo</option>';
    filtroMotor.disabled = true;
    productosCompatibles = [];
    ocultarInfoFiltro();
    aplicarFiltros();
}

function ocultarInfoFiltro() {
    document.getElementById('infoFiltroVehiculo').style.display = 'none';
}

function aplicarFiltros() {
    const textoBusqueda = buscarProducto ? buscarProducto.value.toLowerCase() : '';
    const soloStockBajo = filtroStockBajo ? filtroStockBajo.checked : false;
    const mostrarInactivos = filtroInactivos ? filtroInactivos.checked : false;
    const soloPedidos = filtroSoloPedidos ? filtroSoloPedidos.checked : false;
    const hayFiltroVehiculo = productosCompatibles.length > 0;
    
    if (!tablaProductos) return;
    
    const tbody = tablaProductos.getElementsByTagName('tbody')[0];
    if (!tbody) return;
    
    const filas = tbody.getElementsByTagName('tr');
    
    let visibles = 0;
    const total = filas.length;
    
    for (let fila of filas) {
        // Obtener datos de la fila
        const textoFila = fila.textContent.toLowerCase();
        const esStockBajo = fila.getAttribute('data-stock-bajo') === 'true';
        const esActivo = fila.getAttribute('data-activo') === 'true';
        const tienePedido = fila.getAttribute('data-pedido') === 'true';
        
        // Obtener ID del producto (de la URL de editar)
        const linkEditar = fila.querySelector('a[href*="/editar_variante/"]');
        const idProducto = linkEditar ? parseInt(linkEditar.href.split('/').pop()) : null;
        
        // Aplicar filtros
        let mostrar = true;
        
        // Filtro de búsqueda
        if (textoBusqueda && !textoFila.includes(textoBusqueda)) {
            mostrar = false;
        }
        
        // Filtro de stock bajo
        if (soloStockBajo && !esStockBajo) {
            mostrar = false;
        }
        
        // Filtro de inactivos (si está marcado, mostrar SOLO inactivos)
        if (mostrarInactivos) {
            if (esActivo) {
                mostrar = false;
            }
        } else {
            // Si NO está marcado, ocultar inactivos
            if (!esActivo) {
                mostrar = false;
            }
        }
        
        // Filtro de pedidos activos
        if (soloPedidos && !tienePedido) {
            mostrar = false;
        }
        
        // FILTRO POR VEHÍCULO (el más importante)
        // Si hay filtro activo de vehículo, SOLO mostrar productos en la lista
        if (hayFiltroVehiculo && idProducto) {
            if (!productosCompatibles.includes(idProducto)) {
                mostrar = false;
            }
        }
        
        // Mostrar u ocultar fila
        fila.style.display = mostrar ? '' : 'none';
        
        if (mostrar) visibles++;
    }
    
    // Actualizar contador
    const contador = document.getElementById('contadorProductos');
    if (contador) {
        contador.textContent = `Mostrando ${visibles} de ${total} productos`;
    }
}

// Event listeners para otros filtros
if (buscarProducto) {
    buscarProducto.addEventListener('input', aplicarFiltros);
}

if (filtroStockBajo) {
    filtroStockBajo.addEventListener('change', aplicarFiltros);
}

if (filtroInactivos) {
    filtroInactivos.addEventListener('change', aplicarFiltros);
}

if (filtroSoloPedidos) {
    filtroSoloPedidos.addEventListener('change', aplicarFiltros);
}

// Aplicar filtros al cargar (para ocultar inactivos por defecto)
document.addEventListener('DOMContentLoaded', function() {
    aplicarFiltros();
});