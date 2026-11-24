# Synthetic example common.mk (written for qnxbuild-lint tests).
# Follows the QNX recursive-make convention.
ifndef QCONFIG
QCONFIG=qconfig.mk
endif
include $(QCONFIG)

ifndef NAME
NAME=myapp
endif

USEFILE=$(PROJECT_ROOT)/src/myapp/myapp.use
INSTALLDIR=bin

include $(MKFILES_ROOT)/qmacros.mk
include $(MKFILES_ROOT)/qtargets.mk

INSTALL_ROOT_nto = $(PROJECT_ROOT)/install
USE_INSTALL_ROOT=1
