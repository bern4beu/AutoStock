document.addEventListener('DOMContentLoaded', function() {
    
    const form = document.getElementById('formProductoVehiculo');
    const mensaje = document.getElementById('mensaje');
    const selectVehiculos = document.getElementById('vehiculos');
    
    // Filtros
    const filtroMarca = document.getElementById('filtroMarcaVehiculo');
    const filtroModelo = document.getElementById('filtroModeloVehiculo');
    const filtroMotor = document.getElementById('filtroMotorVehiculo');
    const btnLimpiar = document.getElementById('btnLimpiarFiltroVehiculo');
    
    // Si no hay select, salir
    if (!selectVehiculos) return;
    
    const todasLasOpciones = Array.from(selectVehiculos.options);

    // Permitir selección múltiple sin Ctrl
    selectVehiculos.addEventListener('mousedown', function(e) {
        e.preventDefault();
        
        const option = e.target;
        
        if (option.tagName === 'OPTION') {
            option.selected = !option.selected;
            
            // Disparar evento change para que se actualice
            selectVehiculos.dispatchEvent(new Event('change'));
            
            return false;
        }
    });

    // Evitar comportamiento por defecto de selección
    selectVehiculos.addEventListener('click', function(e) {
        e.preventDefault();
    });
    
    // ========== CARGAR MARCAS AL INICIO ==========
    
    const marcasUnicas = [...new Set(todasLasOpciones.map(opt => opt.dataset.marca))].sort();
    
    marcasUnicas.forEach(marca => {
        const option = document.createElement('option');
        option.value = marca;
        option.textContent = marca;
        filtroMarca.appendChild(option);
    });
    
    // ========== EVENTOS DE FILTROS ==========
    
    filtroMarca.addEventListener('change', function() {
        const marca = this.value;
        
        // Resetear modelos y motores
        filtroModelo.innerHTML = '<option value="">-- Todos --</option>';
        filtroMotor.innerHTML = '<option value="">-- Todos --</option>';
        filtroModelo.disabled = true;
        filtroMotor.disabled = true;
        
        if (!marca) {
            aplicarFiltros();
            return;
        }
        
        // Cargar modelos de la marca seleccionada
        const modelosUnicas = [...new Set(
            todasLasOpciones
                .filter(opt => opt.dataset.marca === marca)
                .map(opt => opt.dataset.modelo)
        )].sort();
        
        modelosUnicas.forEach(modelo => {
            const option = document.createElement('option');
            option.value = modelo;
            option.textContent = modelo;
            filtroModelo.appendChild(option);
        });
        
        filtroModelo.disabled = false;
        aplicarFiltros();
    });
    
    filtroModelo.addEventListener('change', function() {
        const marca = filtroMarca.value;
        const modelo = this.value;
        
        // Resetear motores
        filtroMotor.innerHTML = '<option value="">-- Todos --</option>';
        filtroMotor.disabled = true;
        
        if (!modelo) {
            aplicarFiltros();
            return;
        }
        
        // Cargar motores del modelo seleccionado
        const motoresUnicas = [...new Set(
            todasLasOpciones
                .filter(opt => opt.dataset.marca === marca && opt.dataset.modelo === modelo)
                .map(opt => opt.dataset.motor || 'Sin motor')
        )].sort();
        
        motoresUnicas.forEach(motor => {
            const option = document.createElement('option');
            option.value = motor;
            option.textContent = motor;
            filtroMotor.appendChild(option);
        });
        
        filtroMotor.disabled = false;
        aplicarFiltros();
    });
    
    filtroMotor.addEventListener('change', aplicarFiltros);
    
    btnLimpiar.addEventListener('click', function() {
        // Limpiar filtros
        filtroMarca.value = '';
        filtroModelo.innerHTML = '<option value="">-- Todos --</option>';
        filtroMotor.innerHTML = '<option value="">-- Todos --</option>';
        filtroModelo.disabled = true;
        filtroMotor.disabled = true;
        
        // MANTENER las selecciones, solo quitar el filtro
        aplicarFiltros();
    });
    
    // ========== APLICAR FILTROS ==========
    
    // Variable para mantener las selecciones
    let vehiculosSeleccionados = new Set();

    function aplicarFiltros() {
        const marcaSeleccionada = filtroMarca.value;
        const modeloSeleccionado = filtroModelo.value;
        const motorSeleccionado = filtroMotor.value;
        
        // Guardar selecciones actuales antes de filtrar
        Array.from(selectVehiculos.selectedOptions).forEach(opt => {
            vehiculosSeleccionados.add(opt.value);
        });
        
        // Si no hay filtros, mostrar todos
        if (!marcaSeleccionada && !modeloSeleccionado && !motorSeleccionado) {
            selectVehiculos.innerHTML = '';
            todasLasOpciones.forEach(opt => {
                const clone = opt.cloneNode(true);
                // Restaurar selección si estaba seleccionado
                if (vehiculosSeleccionados.has(opt.value)) {
                    clone.selected = true;
                }
                selectVehiculos.appendChild(clone);
            });
            // Actualizar estilos
            selectVehiculos.dispatchEvent(new Event('change'));
            return;
        }
        
        // Filtrar y reconstruir el select
        selectVehiculos.innerHTML = '';
        
        todasLasOpciones.forEach(option => {
            const marca = option.dataset.marca;
            const modelo = option.dataset.modelo;
            const motor = option.dataset.motor || 'Sin motor';
            
            let incluir = true;
            
            if (marcaSeleccionada && marca !== marcaSeleccionada) {
                incluir = false;
            }
            
            if (modeloSeleccionado && modelo !== modeloSeleccionado) {
                incluir = false;
            }
            
            if (motorSeleccionado && motor !== motorSeleccionado) {
                incluir = false;
            }
            
            if (incluir) {
                const clone = option.cloneNode(true);
                // Restaurar selección si estaba seleccionado
                if (vehiculosSeleccionados.has(option.value)) {
                    clone.selected = true;
                }
                selectVehiculos.appendChild(clone);
            }
        });
        
        // Actualizar estilos
        selectVehiculos.dispatchEvent(new Event('change'));
    }
    
    // ========== VALIDACIÓN DEL FORMULARIO ==========
    
    if (form) {
        form.addEventListener('submit', function(e) {
            
            mensaje.classList.remove('show', 'exito', 'error');
            
            const productoBase = document.getElementById('id_producto_base').value;
            const vehiculosSeleccionados = Array.from(selectVehiculos.selectedOptions);
            
            if (productoBase === '') {
                e.preventDefault();
                mostrarMensaje('Por favor seleccioná un producto base', 'error');
                return false;
            }
            
            if (vehiculosSeleccionados.length === 0) {
                e.preventDefault();
                mostrarMensaje('Por favor seleccioná al menos un vehículo', 'error');
                return false;
            }
        });
    }
    
    function mostrarMensaje(texto, tipo) {
        mensaje.textContent = texto;
        mensaje.classList.add('show', tipo);
        
        setTimeout(() => {
            mensaje.classList.remove('show');
        }, 5000);
    }
    
});

// Resaltar visualmente las opciones seleccionadas
selectVehiculos.addEventListener('change', function() {
    Array.from(selectVehiculos.options).forEach(option => {
        if (option.selected) {
            option.style.background = '#4CAF50';
            option.style.color = 'white';
        } else {
            option.style.background = '';
            option.style.color = '';
        }
    });
});