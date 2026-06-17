// editar_variante.js - Cálculo automático de precios con porcentaje de ganancia

const inputPrecioCompra = document.getElementById('precio_compra');
const inputPrecio = document.getElementById('precio');
const inputPorcentaje = document.getElementById('porcentaje_ganancia');

// Crear campo de porcentaje de ganancia si no existe
function agregarCampoPorcentaje() {
    if (inputPorcentaje) return; // Ya existe
    
    const precioVentaGroup = inputPrecio.closest('.form-group');
    if (!precioVentaGroup) return;
    
    // Crear div para el porcentaje
    const porcentajeDiv = document.createElement('div');
    porcentajeDiv.className = 'form-group';
    porcentajeDiv.style.marginBottom = '0';
    porcentajeDiv.innerHTML = `
        <label for="porcentaje_ganancia">% Ganancia (opcional)</label>
        <input 
            type="number" 
            id="porcentaje_ganancia" 
            placeholder="Ej: 30 para 30%"
            step="0.01"
            min="0"
            style="border-color: var(--accent);"
        >
        <small style="color: var(--gray-500); display: block; margin-top: 4px;">
            Calculá el precio de venta automáticamente
        </small>
    `;
    
    // Insertar después del precio de venta
    precioVentaGroup.parentNode.insertBefore(porcentajeDiv, precioVentaGroup.nextSibling);
}

// Calcular precio de venta según precio de compra + porcentaje
function calcularPrecioVenta() {
    const porcentajeInput = document.getElementById('porcentaje_ganancia');
    if (!inputPrecioCompra || !inputPrecio || !porcentajeInput) return;
    
    const precioCompra = parseFloat(inputPrecioCompra.value);
    const porcentaje = parseFloat(porcentajeInput.value);
    
    if (!precioCompra || !porcentaje || precioCompra <= 0 || porcentaje < 0) return;
    
    // Calcular precio de venta
    const precioVenta = precioCompra * (1 + (porcentaje / 100));
    inputPrecio.value = precioVenta.toFixed(2);
    
    // Resaltar que se calculó automáticamente
    inputPrecio.style.backgroundColor = '#d4edda';
    setTimeout(() => {
        inputPrecio.style.backgroundColor = '';
    }, 1000);
}

// Calcular porcentaje según precios ingresados
function calcularPorcentaje() {
    const porcentajeInput = document.getElementById('porcentaje_ganancia');
    if (!inputPrecioCompra || !inputPrecio || !porcentajeInput) return;
    
    const precioCompra = parseFloat(inputPrecioCompra.value);
    const precioVenta = parseFloat(inputPrecio.value);
    
    if (!precioCompra || !precioVenta || precioCompra <= 0) return;
    
    // Calcular porcentaje de ganancia
    const porcentaje = ((precioVenta - precioCompra) / precioCompra) * 100;
    porcentajeInput.value = porcentaje.toFixed(2);
    
    // Resaltar
    porcentajeInput.style.backgroundColor = '#cfe2ff';
    setTimeout(() => {
        porcentajeInput.style.backgroundColor = '';
    }, 1000);
}

// Inicializar
document.addEventListener('DOMContentLoaded', function() {
    agregarCampoPorcentaje();
    
    const porcentajeInput = document.getElementById('porcentaje_ganancia');
    
    // Event listeners
    if (inputPrecioCompra && porcentajeInput) {
        inputPrecioCompra.addEventListener('input', calcularPrecioVenta);
        porcentajeInput.addEventListener('input', calcularPrecioVenta);
    }
    
    if (inputPrecio && inputPrecioCompra && porcentajeInput) {
        // Si cambia el precio de venta manualmente, calcular porcentaje
        inputPrecio.addEventListener('input', function() {
            // Solo si el porcentaje está vacío
            if (!porcentajeInput.value) {
                calcularPorcentaje();
            }
        });
    }
    
    // Calcular porcentaje inicial si hay ambos precios
    if (inputPrecioCompra && inputPrecio) {
        const precioCompra = parseFloat(inputPrecioCompra.value);
        const precioVenta = parseFloat(inputPrecio.value);
        
        if (precioCompra > 0 && precioVenta > 0) {
            calcularPorcentaje();
        }
    }
});