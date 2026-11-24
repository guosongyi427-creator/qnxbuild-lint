# Synthetic CMake-wrapper common.mk (modelled on qnx-ports
# build-files/ports/FreeImage/common.mk). It drives its own build with
# cmake, defines its own targets, never assigns NAME, and does not
# include qmacros.mk/qtargets.mk. M01/M02/M03 must not fire: this is a
# wrapper, not a standard recursive-make project.
ifndef QCONFIG
QCONFIG=qconfig.mk
endif
include $(QCONFIG)

CMAKE_ARGS = -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=$(INSTALL_ROOT_nto)

ALL_DEPENDENCIES = freeimage_all
.PHONY: freeimage_all

freeimage_all:
	cmake $(CMAKE_ARGS) -S . -B build
	cmake --build build
