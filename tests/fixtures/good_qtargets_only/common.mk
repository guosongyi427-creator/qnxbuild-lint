# Synthetic common.mk: includes qtargets.mk but NOT qmacros.mk.
# qtargets.mk pulls in qmacros.mk, so M02 must not fire for the
# missing qmacros.mk. (Regression test for the qmacros false positive:
# build-files/ports/FreeImage/common.mk includes qtargets.mk but not
# qmacros.mk and was wrongly flagged M02.)
ifndef QCONFIG
QCONFIG=qconfig.mk
endif
include $(QCONFIG)

ifndef NAME
NAME=qtargetsonly
endif

include $(MKFILES_ROOT)/qtargets.mk
