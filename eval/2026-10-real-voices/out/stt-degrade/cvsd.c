/* Bluetooth HFP narrowband CVSD (Core spec v5.x Vol 2 Part B §9.2), encode
 * then decode in one pass: s16le mono at 64 kHz on stdin -> decoded s16le at
 * 64 kHz on stdout (the 1-bit stream is what goes over the air at 64 kbit/s).
 * Parameters from the spec: h = 1-1/32, beta = 1-1/1024, J = K = 4,
 * delta_min = 10, delta_max = 1280, y clamped to s16.
 *   cc -O2 -o cvsd cvsd.c */
#include <stdio.h>
#include <stdint.h>
int main(void) {
  const double h = 1.0 - 1.0 / 32, beta = 1.0 - 1.0 / 1024, dmin = 10, dmax = 1280;
  double xe = 0, d = dmin, xd = 0, dd = dmin; /* encoder / decoder state */
  unsigned hist = 0, dhist = 0;
  int16_t in[4096], out[4096];
  size_t n;
  while ((n = fread(in, 2, 4096, stdin)) > 0) {
    for (size_t i = 0; i < n; i++) {
      int b = in[i] >= xe ? 1 : 0;                       /* encoder */
      hist = ((hist << 1) | b) & 0xF;
      int run = hist == 0xF || hist == 0;
      d = run ? (d + dmin > dmax ? dmax : d + dmin) : (beta * d < dmin ? dmin : beta * d);
      double y = xe + (b ? d : -d);
      if (y > 32767) y = 32767; if (y < -32768) y = -32768;
      xe = h * y;
      dhist = ((dhist << 1) | b) & 0xF;                  /* decoder, same bit */
      int drun = dhist == 0xF || dhist == 0;
      dd = drun ? (dd + dmin > dmax ? dmax : dd + dmin) : (beta * dd < dmin ? dmin : beta * dd);
      double yd = xd + (b ? dd : -dd);
      if (yd > 32767) yd = 32767; if (yd < -32768) yd = -32768;
      xd = h * yd;
      out[i] = (int16_t)yd;
    }
    fwrite(out, 2, n, stdout);
  }
  return 0;
}
