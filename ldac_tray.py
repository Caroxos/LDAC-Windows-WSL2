import sys
import os

# Agregar la ruta local al path de importación
INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))
if INSTALL_DIR not in sys.path:
    sys.path.insert(0, INSTALL_DIR)

import main

if __name__ == "__main__":
    main.main()
