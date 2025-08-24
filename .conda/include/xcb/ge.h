/*
 * This file generated automatically from ge.xml by c_client.py.
 * Edit at your peril.
 */

/**
 * @defgroup XCB_GenericEvent_API XCB GenericEvent API
 * @brief GenericEvent XCB Protocol Implementation.
 * @{
 **/

#ifndef __GE_H
#define __GE_H

#include "xcb.h"

#ifdef __cplusplus
extern "C" {
#endif

#define XCB_GENERICEVENT_MAJOR_VERSION 1
#define XCB_GENERICEVENT_MINOR_VERSION 0

extern xcb_extension_t xcb_genericevent_id;

/**
 * @brief xcb_genericevent_query_version_cookie_t
 **/
typedef struct xcb_genericevent_query_version_cookie_t {
    unsigned int sequence;
} xcb_genericevent_query_version_cookie_t;

/** Opcode for xcb_genericevent_query_version. */
#define XCB_GENERICEVENT_QUERY_VERSION 0

/**
 * @brief xcb_genericevent_query_version_request_t
 **/
typedef struct xcb_genericevent_query_version_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint16_t client_major_version;
    uint16_t client_minor_version;
} xcb_genericevent_query_version_request_t;

/**
 * @brief xcb_genericevent_query_version_reply_t
 **/
typedef struct xcb_genericevent_query_version_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t major_version;
    uint16_t minor_version;
    uint8_t  pad1[20];
} xcb_genericevent_query_version_reply_t;

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_genericevent_query_version_cookie_t
xcb_genericevent_query_version (xcb_connection_t *c,
                                uint16_t          client_major_version,
                                uint16_t          client_minor_version);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_genericevent_query_version_cookie_t
xcb_genericevent_query_version_unchecked (xcb_connection_t *c,
                                          uint16_t          client_major_version,
                                          uint16_t          client_minor_version);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_genericevent_query_version_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_genericevent_query_version_reply_t *
xcb_genericevent_query_version_reply (xcb_connection_t                         *c,
                                      xcb_genericevent_query_version_cookie_t   cookie  /**< */,
                                      xcb_generic_error_t                     **e);


#ifdef __cplusplus
}
#endif

#endif

/**
 * @}
 */
