/*
 * nnpa_check.c - Ask the IBM zDNN library whether the Telum Integrated
 * Accelerator for AI (NNPA) is usable from this LinuxONE guest.
 *
 * The `nnpa` flag in /proc/cpuinfo only says the CPU advertises the facility;
 * this program confirms that the z/VM guest can actually issue NNPA
 * instructions (query functions used by matmul and element-wise ops).
 *
 * Build and run on the VM (needs the libzdnn-dev package):
 *     gcc -O2 -o nnpa_check nnpa_check.c -lzdnn && ./nnpa_check
 * Exit code: 0 when NNPA is available, 1 otherwise.
 */
#include <stdio.h>
#include <zdnn.h>

int main(void) {
  zdnn_init();

  const uint32_t version = zdnn_get_library_version();
  const bool installed = zdnn_is_nnpa_installed();
  /* Matrix multiplication and addition are the ops a dense/tree model needs. */
  const bool has_matmul = zdnn_is_nnpa_function_installed(1, NNPA_MATMUL_OP);
  const bool has_add = zdnn_is_nnpa_function_installed(1, NNPA_ADD);

  printf("zdnn_library_version=0x%06x\n", version);
  printf("nnpa_installed=%s\n", installed ? "yes" : "no");
  printf("nnpa_matmul_op=%s\n", has_matmul ? "yes" : "no");
  printf("nnpa_add=%s\n", has_add ? "yes" : "no");
  printf("nnpa_max_dim_idx_size=%u\n", zdnn_get_nnpa_max_dim_idx_size());
  printf("zdnn_max_runnable_version=0x%06x\n", zdnn_get_max_runnable_version());
  return installed ? 0 : 1;
}
