/* Synthetic broken C source (written for qnxbuild-lint tests).
 * Every QNX API misuse below is deliberate.
 */
#include <sys/neutrino.h>

int main(void)
{
    /* C01: first argument is not a _NTO_TCTL_* constant */
    ThreadCtl(0, 0);

    /* C06: flags argument is neither 0 nor _NTO_CHF_* */
    /* C02 does not fire: name_attach() is present below */
    int chid = ChannelCreate(1);

    /* C03: no dispatch_create / dispatch_context_alloc in this file */
    resmgr_attach(NULL, NULL, "/dev/x", _FTYPE_ANY, 0,
                  NULL, NULL, NULL);

    /* C04: no name_detach() in this file */
    name_attach(NULL, "x", 0);

    /* C05: no InterruptDetach() in this file */
    InterruptAttach(4, NULL, NULL, 0, 0);

    (void)chid;
    return 0;
}
