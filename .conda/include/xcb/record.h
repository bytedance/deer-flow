/*
 * This file generated automatically from record.xml by c_client.py.
 * Edit at your peril.
 */

/**
 * @defgroup XCB_Record_API XCB Record API
 * @brief Record XCB Protocol Implementation.
 * @{
 **/

#ifndef __RECORD_H
#define __RECORD_H

#include "xcb.h"

#ifdef __cplusplus
extern "C" {
#endif

#define XCB_RECORD_MAJOR_VERSION 1
#define XCB_RECORD_MINOR_VERSION 13

extern xcb_extension_t xcb_record_id;

typedef uint32_t xcb_record_context_t;

/**
 * @brief xcb_record_context_iterator_t
 **/
typedef struct xcb_record_context_iterator_t {
    xcb_record_context_t *data;
    int                   rem;
    int                   index;
} xcb_record_context_iterator_t;

/**
 * @brief xcb_record_range_8_t
 **/
typedef struct xcb_record_range_8_t {
    uint8_t first;
    uint8_t last;
} xcb_record_range_8_t;

/**
 * @brief xcb_record_range_8_iterator_t
 **/
typedef struct xcb_record_range_8_iterator_t {
    xcb_record_range_8_t *data;
    int                   rem;
    int                   index;
} xcb_record_range_8_iterator_t;

/**
 * @brief xcb_record_range_16_t
 **/
typedef struct xcb_record_range_16_t {
    uint16_t first;
    uint16_t last;
} xcb_record_range_16_t;

/**
 * @brief xcb_record_range_16_iterator_t
 **/
typedef struct xcb_record_range_16_iterator_t {
    xcb_record_range_16_t *data;
    int                    rem;
    int                    index;
} xcb_record_range_16_iterator_t;

/**
 * @brief xcb_record_ext_range_t
 **/
typedef struct xcb_record_ext_range_t {
    xcb_record_range_8_t  major;
    xcb_record_range_16_t minor;
} xcb_record_ext_range_t;

/**
 * @brief xcb_record_ext_range_iterator_t
 **/
typedef struct xcb_record_ext_range_iterator_t {
    xcb_record_ext_range_t *data;
    int                     rem;
    int                     index;
} xcb_record_ext_range_iterator_t;

/**
 * @brief xcb_record_range_t
 **/
typedef struct xcb_record_range_t {
    xcb_record_range_8_t   core_requests;
    xcb_record_range_8_t   core_replies;
    xcb_record_ext_range_t ext_requests;
    xcb_record_ext_range_t ext_replies;
    xcb_record_range_8_t   delivered_events;
    xcb_record_range_8_t   device_events;
    xcb_record_range_8_t   errors;
    uint8_t                client_started;
    uint8_t                client_died;
} xcb_record_range_t;

/**
 * @brief xcb_record_range_iterator_t
 **/
typedef struct xcb_record_range_iterator_t {
    xcb_record_range_t *data;
    int                 rem;
    int                 index;
} xcb_record_range_iterator_t;

typedef uint8_t xcb_record_element_header_t;

/**
 * @brief xcb_record_element_header_iterator_t
 **/
typedef struct xcb_record_element_header_iterator_t {
    xcb_record_element_header_t *data;
    int                          rem;
    int                          index;
} xcb_record_element_header_iterator_t;

typedef enum xcb_record_h_type_t {
    XCB_RECORD_H_TYPE_FROM_SERVER_TIME = 1,
    XCB_RECORD_H_TYPE_FROM_CLIENT_TIME = 2,
    XCB_RECORD_H_TYPE_FROM_CLIENT_SEQUENCE = 4
} xcb_record_h_type_t;

typedef uint32_t xcb_record_client_spec_t;

/**
 * @brief xcb_record_client_spec_iterator_t
 **/
typedef struct xcb_record_client_spec_iterator_t {
    xcb_record_client_spec_t *data;
    int                       rem;
    int                       index;
} xcb_record_client_spec_iterator_t;

typedef enum xcb_record_cs_t {
    XCB_RECORD_CS_CURRENT_CLIENTS = 1,
    XCB_RECORD_CS_FUTURE_CLIENTS = 2,
    XCB_RECORD_CS_ALL_CLIENTS = 3
} xcb_record_cs_t;

/**
 * @brief xcb_record_client_info_t
 **/
typedef struct xcb_record_client_info_t {
    xcb_record_client_spec_t client_resource;
    uint32_t                 num_ranges;
} xcb_record_client_info_t;

/**
 * @brief xcb_record_client_info_iterator_t
 **/
typedef struct xcb_record_client_info_iterator_t {
    xcb_record_client_info_t *data;
    int                       rem;
    int                       index;
} xcb_record_client_info_iterator_t;

/** Opcode for xcb_record_bad_context. */
#define XCB_RECORD_BAD_CONTEXT 0

/**
 * @brief xcb_record_bad_context_error_t
 **/
typedef struct xcb_record_bad_context_error_t {
    uint8_t  response_type;
    uint8_t  error_code;
    uint16_t sequence;
    uint32_t invalid_record;
    uint16_t minor_opcode;
    uint8_t  major_opcode;
} xcb_record_bad_context_error_t;

/**
 * @brief xcb_record_query_version_cookie_t
 **/
typedef struct xcb_record_query_version_cookie_t {
    unsigned int sequence;
} xcb_record_query_version_cookie_t;

/** Opcode for xcb_record_query_version. */
#define XCB_RECORD_QUERY_VERSION 0

/**
 * @brief xcb_record_query_version_request_t
 **/
typedef struct xcb_record_query_version_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint16_t major_version;
    uint16_t minor_version;
} xcb_record_query_version_request_t;

/**
 * @brief xcb_record_query_version_reply_t
 **/
typedef struct xcb_record_query_version_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t major_version;
    uint16_t minor_version;
} xcb_record_query_version_reply_t;

/** Opcode for xcb_record_create_context. */
#define XCB_RECORD_CREATE_CONTEXT 1

/**
 * @brief xcb_record_create_context_request_t
 **/
typedef struct xcb_record_create_context_request_t {
    uint8_t                     major_opcode;
    uint8_t                     minor_opcode;
    uint16_t                    length;
    xcb_record_context_t        context;
    xcb_record_element_header_t element_header;
    uint8_t                     pad0[3];
    uint32_t                    num_client_specs;
    uint32_t                    num_ranges;
} xcb_record_create_context_request_t;

/** Opcode for xcb_record_register_clients. */
#define XCB_RECORD_REGISTER_CLIENTS 2

/**
 * @brief xcb_record_register_clients_request_t
 **/
typedef struct xcb_record_register_clients_request_t {
    uint8_t                     major_opcode;
    uint8_t                     minor_opcode;
    uint16_t                    length;
    xcb_record_context_t        context;
    xcb_record_element_header_t element_header;
    uint8_t                     pad0[3];
    uint32_t                    num_client_specs;
    uint32_t                    num_ranges;
} xcb_record_register_clients_request_t;

/** Opcode for xcb_record_unregister_clients. */
#define XCB_RECORD_UNREGISTER_CLIENTS 3

/**
 * @brief xcb_record_unregister_clients_request_t
 **/
typedef struct xcb_record_unregister_clients_request_t {
    uint8_t              major_opcode;
    uint8_t              minor_opcode;
    uint16_t             length;
    xcb_record_context_t context;
    uint32_t             num_client_specs;
} xcb_record_unregister_clients_request_t;

/**
 * @brief xcb_record_get_context_cookie_t
 **/
typedef struct xcb_record_get_context_cookie_t {
    unsigned int sequence;
} xcb_record_get_context_cookie_t;

/** Opcode for xcb_record_get_context. */
#define XCB_RECORD_GET_CONTEXT 4

/**
 * @brief xcb_record_get_context_request_t
 **/
typedef struct xcb_record_get_context_request_t {
    uint8_t              major_opcode;
    uint8_t              minor_opcode;
    uint16_t             length;
    xcb_record_context_t context;
} xcb_record_get_context_request_t;

/**
 * @brief xcb_record_get_context_reply_t
 **/
typedef struct xcb_record_get_context_reply_t {
    uint8_t                     response_type;
    uint8_t                     enabled;
    uint16_t                    sequence;
    uint32_t                    length;
    xcb_record_element_header_t element_header;
    uint8_t                     pad0[3];
    uint32_t                    num_intercepted_clients;
    uint8_t                     pad1[16];
} xcb_record_get_context_reply_t;

/**
 * @brief xcb_record_enable_context_cookie_t
 **/
typedef struct xcb_record_enable_context_cookie_t {
    unsigned int sequence;
} xcb_record_enable_context_cookie_t;

/** Opcode for xcb_record_enable_context. */
#define XCB_RECORD_ENABLE_CONTEXT 5

/**
 * @brief xcb_record_enable_context_request_t
 **/
typedef struct xcb_record_enable_context_request_t {
    uint8_t              major_opcode;
    uint8_t              minor_opcode;
    uint16_t             length;
    xcb_record_context_t context;
} xcb_record_enable_context_request_t;

/**
 * @brief xcb_record_enable_context_reply_t
 **/
typedef struct xcb_record_enable_context_reply_t {
    uint8_t                     response_type;
    uint8_t                     category;
    uint16_t                    sequence;
    uint32_t                    length;
    xcb_record_element_header_t element_header;
    uint8_t                     client_swapped;
    uint8_t                     pad0[2];
    uint32_t                    xid_base;
    uint32_t                    server_time;
    uint32_t                    rec_sequence_num;
    uint8_t                     pad1[8];
} xcb_record_enable_context_reply_t;

/** Opcode for xcb_record_disable_context. */
#define XCB_RECORD_DISABLE_CONTEXT 6

/**
 * @brief xcb_record_disable_context_request_t
 **/
typedef struct xcb_record_disable_context_request_t {
    uint8_t              major_opcode;
    uint8_t              minor_opcode;
    uint16_t             length;
    xcb_record_context_t context;
} xcb_record_disable_context_request_t;

/** Opcode for xcb_record_free_context. */
#define XCB_RECORD_FREE_CONTEXT 7

/**
 * @brief xcb_record_free_context_request_t
 **/
typedef struct xcb_record_free_context_request_t {
    uint8_t              major_opcode;
    uint8_t              minor_opcode;
    uint16_t             length;
    xcb_record_context_t context;
} xcb_record_free_context_request_t;

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_record_context_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_record_context_t)
 */
void
xcb_record_context_next (xcb_record_context_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_record_context_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_record_context_end (xcb_record_context_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_record_range_8_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_record_range_8_t)
 */
void
xcb_record_range_8_next (xcb_record_range_8_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_record_range_8_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_record_range_8_end (xcb_record_range_8_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_record_range_16_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_record_range_16_t)
 */
void
xcb_record_range_16_next (xcb_record_range_16_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_record_range_16_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_record_range_16_end (xcb_record_range_16_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_record_ext_range_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_record_ext_range_t)
 */
void
xcb_record_ext_range_next (xcb_record_ext_range_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_record_ext_range_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_record_ext_range_end (xcb_record_ext_range_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_record_range_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_record_range_t)
 */
void
xcb_record_range_next (xcb_record_range_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_record_range_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_record_range_end (xcb_record_range_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_record_element_header_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_record_element_header_t)
 */
void
xcb_record_element_header_next (xcb_record_element_header_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_record_element_header_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_record_element_header_end (xcb_record_element_header_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_record_client_spec_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_record_client_spec_t)
 */
void
xcb_record_client_spec_next (xcb_record_client_spec_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_record_client_spec_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_record_client_spec_end (xcb_record_client_spec_iterator_t i);

int
xcb_record_client_info_sizeof (const void  *_buffer);

xcb_record_range_t *
xcb_record_client_info_ranges (const xcb_record_client_info_t *R);

int
xcb_record_client_info_ranges_length (const xcb_record_client_info_t *R);

xcb_record_range_iterator_t
xcb_record_client_info_ranges_iterator (const xcb_record_client_info_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_record_client_info_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_record_client_info_t)
 */
void
xcb_record_client_info_next (xcb_record_client_info_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_record_client_info_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_record_client_info_end (xcb_record_client_info_iterator_t i);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_record_query_version_cookie_t
xcb_record_query_version (xcb_connection_t *c,
                          uint16_t          major_version,
                          uint16_t          minor_version);

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
xcb_record_query_version_cookie_t
xcb_record_query_version_unchecked (xcb_connection_t *c,
                                    uint16_t          major_version,
                                    uint16_t          minor_version);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_record_query_version_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_record_query_version_reply_t *
xcb_record_query_version_reply (xcb_connection_t                   *c,
                                xcb_record_query_version_cookie_t   cookie  /**< */,
                                xcb_generic_error_t               **e);

int
xcb_record_create_context_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_record_create_context_checked (xcb_connection_t               *c,
                                   xcb_record_context_t            context,
                                   xcb_record_element_header_t     element_header,
                                   uint32_t                        num_client_specs,
                                   uint32_t                        num_ranges,
                                   const xcb_record_client_spec_t *client_specs,
                                   const xcb_record_range_t       *ranges);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_record_create_context (xcb_connection_t               *c,
                           xcb_record_context_t            context,
                           xcb_record_element_header_t     element_header,
                           uint32_t                        num_client_specs,
                           uint32_t                        num_ranges,
                           const xcb_record_client_spec_t *client_specs,
                           const xcb_record_range_t       *ranges);

xcb_record_client_spec_t *
xcb_record_create_context_client_specs (const xcb_record_create_context_request_t *R);

int
xcb_record_create_context_client_specs_length (const xcb_record_create_context_request_t *R);

xcb_generic_iterator_t
xcb_record_create_context_client_specs_end (const xcb_record_create_context_request_t *R);

xcb_record_range_t *
xcb_record_create_context_ranges (const xcb_record_create_context_request_t *R);

int
xcb_record_create_context_ranges_length (const xcb_record_create_context_request_t *R);

xcb_record_range_iterator_t
xcb_record_create_context_ranges_iterator (const xcb_record_create_context_request_t *R);

int
xcb_record_register_clients_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_record_register_clients_checked (xcb_connection_t               *c,
                                     xcb_record_context_t            context,
                                     xcb_record_element_header_t     element_header,
                                     uint32_t                        num_client_specs,
                                     uint32_t                        num_ranges,
                                     const xcb_record_client_spec_t *client_specs,
                                     const xcb_record_range_t       *ranges);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_record_register_clients (xcb_connection_t               *c,
                             xcb_record_context_t            context,
                             xcb_record_element_header_t     element_header,
                             uint32_t                        num_client_specs,
                             uint32_t                        num_ranges,
                             const xcb_record_client_spec_t *client_specs,
                             const xcb_record_range_t       *ranges);

xcb_record_client_spec_t *
xcb_record_register_clients_client_specs (const xcb_record_register_clients_request_t *R);

int
xcb_record_register_clients_client_specs_length (const xcb_record_register_clients_request_t *R);

xcb_generic_iterator_t
xcb_record_register_clients_client_specs_end (const xcb_record_register_clients_request_t *R);

xcb_record_range_t *
xcb_record_register_clients_ranges (const xcb_record_register_clients_request_t *R);

int
xcb_record_register_clients_ranges_length (const xcb_record_register_clients_request_t *R);

xcb_record_range_iterator_t
xcb_record_register_clients_ranges_iterator (const xcb_record_register_clients_request_t *R);

int
xcb_record_unregister_clients_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_record_unregister_clients_checked (xcb_connection_t               *c,
                                       xcb_record_context_t            context,
                                       uint32_t                        num_client_specs,
                                       const xcb_record_client_spec_t *client_specs);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_record_unregister_clients (xcb_connection_t               *c,
                               xcb_record_context_t            context,
                               uint32_t                        num_client_specs,
                               const xcb_record_client_spec_t *client_specs);

xcb_record_client_spec_t *
xcb_record_unregister_clients_client_specs (const xcb_record_unregister_clients_request_t *R);

int
xcb_record_unregister_clients_client_specs_length (const xcb_record_unregister_clients_request_t *R);

xcb_generic_iterator_t
xcb_record_unregister_clients_client_specs_end (const xcb_record_unregister_clients_request_t *R);

int
xcb_record_get_context_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_record_get_context_cookie_t
xcb_record_get_context (xcb_connection_t     *c,
                        xcb_record_context_t  context);

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
xcb_record_get_context_cookie_t
xcb_record_get_context_unchecked (xcb_connection_t     *c,
                                  xcb_record_context_t  context);

int
xcb_record_get_context_intercepted_clients_length (const xcb_record_get_context_reply_t *R);

xcb_record_client_info_iterator_t
xcb_record_get_context_intercepted_clients_iterator (const xcb_record_get_context_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_record_get_context_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_record_get_context_reply_t *
xcb_record_get_context_reply (xcb_connection_t                 *c,
                              xcb_record_get_context_cookie_t   cookie  /**< */,
                              xcb_generic_error_t             **e);

int
xcb_record_enable_context_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_record_enable_context_cookie_t
xcb_record_enable_context (xcb_connection_t     *c,
                           xcb_record_context_t  context);

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
xcb_record_enable_context_cookie_t
xcb_record_enable_context_unchecked (xcb_connection_t     *c,
                                     xcb_record_context_t  context);

uint8_t *
xcb_record_enable_context_data (const xcb_record_enable_context_reply_t *R);

int
xcb_record_enable_context_data_length (const xcb_record_enable_context_reply_t *R);

xcb_generic_iterator_t
xcb_record_enable_context_data_end (const xcb_record_enable_context_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_record_enable_context_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_record_enable_context_reply_t *
xcb_record_enable_context_reply (xcb_connection_t                    *c,
                                 xcb_record_enable_context_cookie_t   cookie  /**< */,
                                 xcb_generic_error_t                **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_record_disable_context_checked (xcb_connection_t     *c,
                                    xcb_record_context_t  context);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_record_disable_context (xcb_connection_t     *c,
                            xcb_record_context_t  context);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_record_free_context_checked (xcb_connection_t     *c,
                                 xcb_record_context_t  context);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_record_free_context (xcb_connection_t     *c,
                         xcb_record_context_t  context);


#ifdef __cplusplus
}
#endif

#endif

/**
 * @}
 */
