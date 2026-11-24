/* Synthetic example C source (written for qnxbuild-lint tests).
 * Uses QNX Neutrino APIs the way the documentation prescribes.
 */
#include <sys/neutrino.h>
#include <sys/resmgr.h>
#include <sys/dispatch.h>
#include <sys/name.h>

int main(void)
{
    ThreadCtl(_NTO_TCTL_IO, 0);

    int chid = ChannelCreate(0);
    int coid = ConnectAttach(0, 0, chid, 0, 0);

    dispatch_t *dpp = dispatch_create();
    resmgr_attach(dpp, NULL, "/dev/myapp", _FTYPE_ANY, 0,
                  NULL, NULL, NULL);

    name_attach_t *attach = name_attach(NULL, "myapp", 0);
    int iid = InterruptAttach(4, NULL, NULL, 0, 0);

    name_detach(attach, 0);
    InterruptDetach(iid);
    (void)coid;
    return 0;
}
