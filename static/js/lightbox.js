document.addEventListener('DOMContentLoaded', function() {
    
    // Crear el lightbox en el DOM
    const lightboxHTML = `
        <div class="lightbox-overlay" id="lightboxOverlay">
            <div class="lightbox-contenido" id="lightboxContenido">
                <button class="lightbox-cerrar" id="lightboxCerrar">✕</button>
                <img class="lightbox-imagen" id="lightboxImagen" src="" alt="">
                <p class="lightbox-caption" id="lightboxCaption"></p>
            </div>
            <p class="lightbox-hint">Click fuera de la imagen para cerrar · ESC para cerrar</p>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', lightboxHTML);
    
    // Referencias
    const overlay = document.getElementById('lightboxOverlay');
    const imagen = document.getElementById('lightboxImagen');
    const caption = document.getElementById('lightboxCaption');
    const cerrar = document.getElementById('lightboxCerrar');
    const contenido = document.getElementById('lightboxContenido');
    
    // Función para abrir el lightbox
    function abrirLightbox(src, alt) {
        imagen.src = src;
        imagen.alt = alt;
        caption.textContent = alt;
        overlay.classList.add('activo');
        document.body.style.overflow = 'hidden'; // Evitar scroll del fondo
    }
    
    // Función para cerrar el lightbox
    function cerrarLightbox() {
        overlay.classList.remove('activo');
        document.body.style.overflow = ''; // Restaurar scroll
        
        // Limpiar imagen después de la animación
        setTimeout(() => {
            imagen.src = '';
        }, 200);
    }
    
    // Detectar clicks en imágenes con clase "imagen-producto"
    // Usamos delegación de eventos para que funcione con imágenes cargadas dinámicamente
    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('imagen-producto')) {
            abrirLightbox(e.target.src, e.target.alt);
        }
    });
    
    // Cerrar al hacer click en el overlay (fuera de la imagen)
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) {
            cerrarLightbox();
        }
    });
    
    // Cerrar con el botón ✕
    cerrar.addEventListener('click', cerrarLightbox);
    
    // Cerrar con la tecla ESC
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && overlay.classList.contains('activo')) {
            cerrarLightbox();
        }
    });
    
    // Evitar que el click en la imagen cierre el lightbox
    contenido.addEventListener('click', function(e) {
        e.stopPropagation();
    });
    
});