/*
 * This file generated automatically from xevie.xml by c_client.py.
 * Edit at your peril.
 */

/**
 * @defgroup XCB_Xevie_API XCB Xevie API
 * @brief Xevie XCB Protocol Implementation.
 * @{
 **/

#ifndef __XEVIE_H
#define __XEVIE_H

#include "xcb.h"

#ifdef __cplusplus
extern "C" {
#endif

#define XCB_XEVIE_MAJOR_VERSION 1
#define XCB_XEVIE_MINOR_VERSION 0

extern xcb_extension_t xcb_xevie_id;

/**
 * @brief xcb_xevie_query_version_cookie_t
 **/
typedef struct xcb_xevie_query_version_cookie_t {
    unsigned int sequence;
} xcb_xevie_query_version_cookie_t;

/** Opcode for xcb_xevie_query_version. */
#define XCB_XEVIE_QUERY_VERSION 0

/**
 * @brief xcb_xevie_query_version_request_t
 **/
typedef struct xcb_xevie_query_version_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint16_t client_major_version;
    uint16_t client_minor_version;
} xcb_xevie_query_version_request_t;

/**
 * @brief xcb_xevie_query_version_reply_t
 **/
typedef struct xcb_xevie_query_version_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t server_major_version;
    uint16_t server_minor_version;
    uint8_t  pad1[20];
} xcb_xevie_query_version_reply_t;

/**
 * @brief xcb_xevie_start_cookie_t
 **/
typedef struct xcb_xevie_start_cookie_t {
    unsigned int sequence;
} xcb_xevie_start_cookie_t;

/** Opcode for xcb_xevie_start. */
#define XCB_XEVIE_START 1

/**
 * @brief xcb_xevie_start_request_t
 **/
typedef struct xcb_xevie_start_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t screen;
} xcb_xevie_start_request_t;

/**
 * @brief xcb_xevie_start_reply_t
 **/
typedef struct xcb_xevie_start_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint8_t  pad1[24];
} xcb_xevie_start_reply_t;

/**
 * @brief xcb_xevie_end_cookie_t
 **/
typedef struct xcb_xevie_end_cookie_t {
    unsigned int sequence;
} xcb_xevie_end_cookie_t;

/** Opcode for xcb_xevie_end. */
#define XCB_XEVIE_END 2

/**
 * @brief xcb_xevie_end_request_t
 **/
typedef struct xcb_xevie_end_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t cmap;
} xcb_xevie_end_request_t;

/**
 * @brief xcb_xevie_end_reply_t
 **/
typedef struct xcb_xevie_end_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint8_t  pad1[24];
} xcb_xevie_end_reply_t;

typedef enum xcb_xevie_datatype_t {
    XCB_XEVIE_DATATYPE_UNMODIFIED = 0,
    XCB_XEVIE_DATATYPE_MODIFIED = 1
} xcb_xevie_datatype_t;

/**
 * @brief xcb_xevie_event_t
 **/
typedef struct xcb_xevie_event_t {
    uint8_t pad0[32];
} xcb_xevie_event_t;

/**
 * @brief xcb_xevie_event_iterator_t
 **/
typedef struct xcb_xevie_event_iterator_t {
    xcb_xevie_event_t *data;
    int                rem;
    int                index;
} xcb_xevie_event_iterator_t;

/**
 * @brief xcb_xevie_send_cookie_t
 **/
typedef struct xcb_xevie_send_cookie_t {
    unsigned int sequence;
} xcb_xevie_send_cookie_t;

/** Opcode for xcb_xevie_send. */
#define XCB_XEVIE_SEND 3

/**
 * @brief xcb_xevie_send_request_t
 **/
typedef struct xcb_xevie_send_request_t {
    uint8_t           major_opcode;
    uint8_t           minor_opcode;
    uint16_t          length;
    xcb_xevie_event_t event;
    uint32_t          data_type;
    uint8_t           pad0[64];
} xcb_xevie_send_request_t;

/**
 * @brief xcb_xevie_send_reply_t
 **/
typedef struct xcb_xevie_send_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint8_t  pad1[24];
} xcb_xevie_send_reply_t;

/**
 * @brief xcb_xevie_select_input_cookie_t
 **/
typedef struct xcb_xevie_select_input_cookie_t {
    unsigned int sequence;
} xcb_xevie_select_input_cookie_t;

/** Opcode for xcb_xevie_select_input. */
#define XCB_XEVIE_SELECT_INPUT 4

/**
 * @brief xcb_xevie_select_input_request_t
 **/
typedef struct xcb_xevie_select_input_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t event_mask;
} xcb_xevie_select_input_request_t;

/**
 * @brief xcb_xevie_select_input_reply_t
 **/
typedef struct xcb_xevie_select_input_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint8_t  pad1[24];
} xcb_xevie_select_input_reply_t;

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xevie_query_version_cookie_t
xcb_xevie_query_version (xcb_connection_t *c,
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
xcb_xevie_query_version_cookie_t
xcb_xevie_query_version_unchecked (xcb_connection_t *c,
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
 * xcb_xevie_query_version_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xevie_query_version_reply_t *
xcb_xevie_query_version_reply (xcb_connection_t                  *c,
                               xcb_xevie_query_version_cookie_t   cookie  /**< */,
                               xcb_generic_error_t              **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xevie_start_cookie_t
xcb_xevie_start (xcb_connection_t *c,
                 uint32_t          screen);

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
xcb_xevie_start_cookie_t
xcb_xevie_start_unchecked (xcb_connection_t *c,
                           uint32_t          screen);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xevie_start_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xevie_start_reply_t *
xcb_xevie_start_reply (xcb_connection_t          *c,
                       xcb_xevie_start_cookie_t   cookie  /**< */,
                       xcb_generic_error_t      **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xevie_end_cookie_t
xcb_xevie_end (xcb_connection_t *c,
               uint32_t          cmap);

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
xcb_xevie_end_cookie_t
xcb_xevie_end_unchecked (xcb_connection_t *c,
                         uint32_t          cmap);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xevie_end_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xevie_end_reply_t *
xcb_xevie_end_reply (xcb_connection_t        *c,
                     xcb_xevie_end_cookie_t   cookie  /**< */,
                     xcb_generic_error_t    **e);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xevie_event_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xevie_event_t)
 */
void
xcb_xevie_event_next (xcb_xevie_event_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xevie_event_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xevie_event_end (xcb_xevie_event_iterator_t i);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xevie_send_cookie_t
xcb_xevie_send (xcb_connection_t  *c,
                xcb_xevie_event_t  event,
                uint32_t           data_type);

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
xcb_xevie_send_cookie_t
xcb_xevie_send_unchecked (xcb_connection_t  *c,
                          xcb_xevie_event_t  event,
                          uint32_t           data_type);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xevie_send_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xevie_send_reply_t *
xcb_xevie_send_reply (xcb_connection_t         *c,
                      xcb_xevie_send_cookie_t   cookie  /**< */,
                      xcb_generic_error_t     **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xevie_select_input_cookie_t
xcb_xevie_select_input (xcb_connection_t *c,
                        uint32_t          event_mask);

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
xcb_xevie_select_input_cookie_t
xcb_xevie_select_input_unchecked (xcb_connection_t *c,
                                  uint32_t          event_mask);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xevie_select_input_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xevie_select_input_reply_t *
xcb_xevie_select_input_reply (xcb_connection_t                 *c,
                              xcb_xevie_select_input_cookie_t   cookie  /**< */,
                              xcb_generic_error_t             **e);


#ifdef __cplusplus
}
#endif

#endif

/**
 * @}
 */
