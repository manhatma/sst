#ifndef _TCPSERVER_H
#define _TCPSERVER_H

#include <time.h>
#include "pico/cyw43_arch.h"
#include "lwip/tcp.h"

struct tcpserver {
    struct tcp_pcb *server_pcb;
    struct tcp_pcb *client_pcb;
    int status;
    int requested_file;
    int64_t requested_time;
    uint32_t requested_time_us;
    int data_len;
    int sent_len;
    s8_t mdns_slot;
    bool mdns_initialized;
};

bool tcpserver_init(struct tcpserver *server);
bool tcpserver_serve(struct tcpserver *server);
void tcpserver_finish(struct tcpserver *server);

#endif /* _TCPSERVER_H */
