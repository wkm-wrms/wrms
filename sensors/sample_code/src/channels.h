#ifndef CHANNELS_H
#define CHANNELS_H

#include <stdint.h>

namespace Channels {
    const uint16_t getSynthRegisterB(uint8_t index);
    const uint16_t getFrequency(uint8_t index);
}

#endif