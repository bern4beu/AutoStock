// venta.js - Gestión de venta con múltiples productos

let productoIndex = 0;
let precios = {};

// Cargar precios al iniciar
fetch('/api/precios_productos')
    .then(r => r.json())
    .then(data => {
        precios = data;
        agregarProducto(); // Agregar primer producto automáticamente
    })
    .catch(err => {
        console.error('Error al cargar precios:', err);
        agregarProducto(); // Agregar de todos modos
    });

function agregarProducto() {
    productoIndex++;
    
    const container = document.getElementById('productos-container');
    if (!container) return;
    
    const div = document.createElement('div');
    div.id = `producto-${productoIndex}`;
    div.style.cssText = 'background: var(--gray-50); padding: var(--spacing-lg); border-radius: 8px; margin-bottom: var(--spacing-md); position: relative;';
    
    div.innerHTML = `
        <button type="button" onclick="eliminarProducto(${productoIndex})" 
                style="position: absolute; top: 12px; right: 12px; background: none; border: none; color: var(--danger); cursor: pointer; padding: 4px;">
            <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>
        </button>
        
        <div style="display: grid; grid-template-columns: 2fr 1fr auto; gap: var(--spacing-md); align-items: flex-end;">
            <div class="form-group" style="margin-bottom: 0;">
                <label>Producto</label>
                <select name="producto_${productoIndex}" id="producto_${productoIndex}" onchange="actualizarSubtotal(${productoIndex})" required>
                    <option value="">Seleccionar producto...</option>
                    ${window.productosDisponibles || ''}
                </select>
            </div>
            
            <div class="form-group" style="margin-bottom: 0;">
                <label>Cantidad</label>
                <input type="number" name="cantidad_${productoIndex}" id="cantidad_${productoIndex}" 
                       min="1" value="1" onchange="actualizarSubtotal(${productoIndex})" required>
            </div>
            
            <div style="padding: 10px 16px; background: white; border-radius: 6px; text-align: right; min-width: 120px;">
                <div style="font-size: var(--text-xs); color: var(--gray-500); margin-bottom: 2px;">Subtotal</div>
                <div id="subtotal_${productoIndex}" style="font-weight: 700; font-size: var(--text-lg); color: var(--gray-900);">$0.00</div>
            </div>
        </div>
    `;
    
    container.appendChild(div);
}

function eliminarProducto(index) {
    const elemento = document.getElementById(`producto-${index}`);
    if (elemento) {
        elemento.remove();
        calcularTotal();
    }
}

function actualizarSubtotal(index) {
    const selectProducto = document.getElementById(`producto_${index}`);
    const inputCantidad = document.getElementById(`cantidad_${index}`);
    const divSubtotal = document.getElementById(`subtotal_${index}`);
    
    if (!selectProducto || !inputCantidad || !divSubtotal) return;
    
    const productoId = selectProducto.value;
    const cantidad = parseFloat(inputCantidad.value) || 0;
    
    if (productoId && precios[productoId]) {
        const precio = precios[productoId];
        const subtotal = precio * cantidad;
        divSubtotal.textContent = `$${subtotal.toFixed(2)}`;
    } else {
        divSubtotal.textContent = '$0.00';
    }
    
    calcularTotal();
}

function calcularTotal() {
    let total = 0;
    
    for (let i = 1; i <= productoIndex; i++) {
        const subtotalElement = document.getElementById(`subtotal_${i}`);
        if (subtotalElement) {
            const subtotal = parseFloat(subtotalElement.textContent.replace('$', '').replace(',', '')) || 0;
            total += subtotal;
        }
    }
    
    const totalElement = document.getElementById('total-venta');
    if (totalElement) {
        totalElement.textContent = `$${total.toFixed(2)}`;
    }
}

// Hacer funciones globales para que el HTML inline pueda llamarlas
window.agregarProducto = agregarProducto;
window.eliminarProducto = eliminarProducto;
window.actualizarSubtotal = actualizarSubtotal;

document.querySelectorAll('input[name="tipo_pago"]').forEach(radio => {
    radio.addEventListener('change', function() {
        document.getElementById('btn_contado').style.background = 
            this.value === 'contado' ? 'var(--primary)' : 'white';
        document.getElementById('btn_contado').style.color = 
            this.value === 'contado' ? 'white' : 'var(--gray-700)';
        document.getElementById('btn_cc').style.background = 
            this.value === 'cuenta_corriente' ? 'var(--primary)' : 'white';
        document.getElementById('btn_cc').style.color = 
            this.value === 'cuenta_corriente' ? 'white' : 'var(--gray-700)';
        document.getElementById('aviso_cc').style.display = 
            this.value === 'cuenta_corriente' ? 'block' : 'none';
    });
});