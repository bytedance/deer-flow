/*
 * This file generated automatically from res.xml by c_client.py.
 * Edit at your peril.
 */

/**
 * @defgroup XCB_Res_API XCB Res API
 * @brief Res XCB Protocol Implementation.
 * @{
 **/

#ifndef __RES_H
#define __RES_H

#include "xcb.h"
#include "xproto.h"

#ifdef __cplusplus
extern "C" {
#endif

#define XCB_RES_MAJOR_VERSION 1
#define XCB_RES_MINOR_VERSION 2

extern xcb_extension_t xcb_res_id;

/**
 * @brief xcb_res_client_t
 **/
typedef struct xcb_res_client_t {
    uint32_t resource_base;
    uint32_t resource_mask;
} xcb_res_client_t;

/**
 * @brief xcb_res_client_iterator_t
 **/
typedef struct xcb_res_client_iterator_t {
    xcb_res_client_t *data;
    int               rem;
    int               index;
} xcb_res_client_iterator_t;

/**
 * @brief xcb_res_type_t
 **/
typedef struct xcb_res_type_t {
    xcb_atom_t resource_type;
    uint32_t   count;
} xcb_res_type_t;

/**
 * @brief xcb_res_type_iterator_t
 **/
typedef struct xcb_res_type_iterator_t {
    xcb_res_type_t *data;
    int             rem;
    int             index;
} xcb_res_type_iterator_t;

typedef enum xcb_res_client_id_mask_t {
    XCB_RES_CLIENT_ID_MASK_CLIENT_XID = 1,
    XCB_RES_CLIENT_ID_MASK_LOCAL_CLIENT_PID = 2
} xcb_res_client_id_mask_t;

/**
 * @brief xcb_res_client_id_spec_t
 **/
typedef struct xcb_res_client_id_spec_t {
    uint32_t client;
    uint32_t mask;
} xcb_res_client_id_spec_t;

/**
 * @brief xcb_res_client_id_spec_iterator_t
 **/
typedef struct xcb_res_client_id_spec_iterator_t {
    xcb_res_client_id_spec_t *data;
    int                       rem;
    int                       index;
} xcb_res_client_id_spec_iterator_t;

/**
 * @brief xcb_res_client_id_value_t
 **/
typedef struct xcb_res_client_id_value_t {
    xcb_res_client_id_spec_t spec;
    uint32_t                 length;
} xcb_res_client_id_value_t;

/**
 * @brief xcb_res_client_id_value_iterator_t
 **/
typedef struct xcb_res_client_id_value_iterator_t {
    xcb_res_client_id_value_t *data;
    int                        rem;
    int                        index;
} xcb_res_client_id_value_iterator_t;

/**
 * @brief xcb_res_resource_id_spec_t
 **/
typedef struct xcb_res_resource_id_spec_t {
    uint32_t resource;
    uint32_t type;
} xcb_res_resource_id_spec_t;

/**
 * @brief xcb_res_resource_id_spec_iterator_t
 **/
typedef struct xcb_res_resource_id_spec_iterator_t {
    xcb_res_resource_id_spec_t *data;
    int                         rem;
    int                         index;
} xcb_res_resource_id_spec_iterator_t;

/**
 * @brief xcb_res_resource_size_spec_t
 **/
typedef struct xcb_res_resource_size_spec_t {
    xcb_res_resource_id_spec_t spec;
    uint32_t                   bytes;
    uint32_t                   ref_count;
    uint32_t                   use_count;
} xcb_res_resource_size_spec_t;

/**
 * @brief xcb_res_resource_size_spec_iterator_t
 **/
typedef struct xcb_res_resource_size_spec_iterator_t {
    xcb_res_resource_size_spec_t *data;
    int                           rem;
    int                           index;
} xcb_res_resource_size_spec_iterator_t;

/**
 * @brief xcb_res_resource_size_value_t
 **/
typedef struct xcb_res_resource_size_value_t {
    xcb_res_resource_size_spec_t size;
    uint32_t                     num_cross_references;
} xcb_res_resource_size_value_t;

/**
 * @brief xcb_res_resource_size_value_iterator_t
 **/
typedef struct xcb_res_resource_size_value_iterator_t {
    xcb_res_resource_size_value_t *data;
    int                            rem;
    int                            index;
} xcb_res_resource_size_value_iterator_t;

/**
 * @brief xcb_res_query_version_cookie_t
 **/
typedef struct xcb_res_query_version_cookie_t {
    unsigned int sequence;
} xcb_res_query_version_cookie_t;

/** Opcode for xcb_res_query_version. */
#define XCB_RES_QUERY_VERSION 0

/**
 * @brief xcb_res_query_version_request_t
 **/
typedef struct xcb_res_query_version_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint8_t  client_major;
    uint8_t  client_minor;
} xcb_res_query_version_request_t;

/**
 * @brief xcb_res_query_version_reply_t
 **/
typedef struct xcb_res_query_version_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t server_major;
    uint16_t server_minor;
} xcb_res_query_version_reply_t;

/**
 * @brief xcb_res_query_clients_cookie_t
 **/
typedef struct xcb_res_query_clients_cookie_t {
    unsigned int sequence;
} xcb_res_query_clients_cookie_t;

/** Opcode for xcb_res_query_clients. */
#define XCB_RES_QUERY_CLIENTS 1

/**
 * @brief xcb_res_query_clients_request_t
 **/
typedef struct xcb_res_query_clients_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
} xcb_res_query_clients_request_t;

/**
 * @brief xcb_res_query_clients_reply_t
 **/
typedef struct xcb_res_query_clients_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t num_clients;
    uint8_t  pad1[20];
} xcb_res_query_clients_reply_t;

/**
 * @brief xcb_res_query_client_resources_cookie_t
 **/
typedef struct xcb_res_query_client_resources_cookie_t {
    unsigned int sequence;
} xcb_res_query_client_resources_cookie_t;

/** Opcode for xcb_res_query_client_resources. */
#define XCB_RES_QUERY_CLIENT_RESOURCES 2

/**
 * @brief xcb_res_query_client_resources_request_t
 **/
typedef struct xcb_res_query_client_resources_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t xid;
} xcb_res_query_client_resources_request_t;

/**
 * @brief xcb_res_query_client_resources_reply_t
 **/
typedef struct xcb_res_query_client_resources_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t num_types;
    uint8_t  pad1[20];
} xcb_res_query_client_resources_reply_t;

/**
 * @brief xcb_res_query_client_pixmap_bytes_cookie_t
 **/
typedef struct xcb_res_query_client_pixmap_bytes_cookie_t {
    unsigned int sequence;
} xcb_res_query_client_pixmap_bytes_cookie_t;

/** Opcode for xcb_res_query_client_pixmap_bytes. */
#define XCB_RES_QUERY_CLIENT_PIXMAP_BYTES 3

/**
 * @brief xcb_res_query_client_pixmap_bytes_request_t
 **/
typedef struct xcb_res_query_client_pixmap_bytes_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t xid;
} xcb_res_query_client_pixmap_bytes_request_t;

/**
 * @brief xcb_res_query_client_pixmap_bytes_reply_t
 **/
typedef struct xcb_res_query_client_pixmap_bytes_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t bytes;
    uint32_t bytes_overflow;
} xcb_res_query_client_pixmap_bytes_reply_t;

/**
 * @brief xcb_res_query_client_ids_cookie_t
 **/
typedef struct xcb_res_query_client_ids_cookie_t {
    unsigned int sequence;
} xcb_res_query_client_ids_cookie_t;

/** Opcode for xcb_res_query_client_ids. */
#define XCB_RES_QUERY_CLIENT_IDS 4

/**
 * @brief xcb_res_query_client_ids_request_t
 **/
typedef struct xcb_res_query_client_ids_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t num_specs;
} xcb_res_query_client_ids_request_t;

/**
 * @brief xcb_res_query_client_ids_reply_t
 **/
typedef struct xcb_res_query_client_ids_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t num_ids;
    uint8_t  pad1[20];
} xcb_res_query_client_ids_reply_t;

/**
 * @brief xcb_res_query_resource_bytes_cookie_t
 **/
typedef struct xcb_res_query_resource_bytes_cookie_t {
    unsigned int sequence;
} xcb_res_query_resource_bytes_cookie_t;

/** Opcode for xcb_res_query_resource_bytes. */
#define XCB_RES_QUERY_RESOURCE_BYTES 5

/**
 * @brief xcb_res_query_resource_bytes_request_t
 **/
typedef struct xcb_res_query_resource_bytes_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t client;
    uint32_t num_specs;
} xcb_res_query_resource_bytes_request_t;

/**
 * @brief xcb_res_query_resource_bytes_reply_t
 **/
typedef struct xcb_res_query_resource_bytes_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t num_sizes;
    uint8_t  pad1[20];
} xcb_res_query_resource_bytes_reply_t;

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_res_client_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_res_client_t)
 */
void
xcb_res_client_next (xcb_res_client_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_res_client_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_res_client_end (xcb_res_client_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_res_type_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_res_type_t)
 */
void
xcb_res_type_next (xcb_res_type_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_res_type_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_res_type_end (xcb_res_type_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_res_client_id_spec_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_res_client_id_spec_t)
 */
void
xcb_res_client_id_spec_next (xcb_res_client_id_spec_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_res_client_id_spec_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_res_client_id_spec_end (xcb_res_client_id_spec_iterator_t i);

int
xcb_res_client_id_value_sizeof (const void  *_buffer);

uint32_t *
xcb_res_client_id_value_value (const xcb_res_client_id_value_t *R);

int
xcb_res_client_id_value_value_length (const xcb_res_client_id_value_t *R);

xcb_generic_iterator_t
xcb_res_client_id_value_value_end (const xcb_res_client_id_value_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_res_client_id_value_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_res_client_id_value_t)
 */
void
xcb_res_client_id_value_next (xcb_res_client_id_value_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_res_client_id_value_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_res_client_id_value_end (xcb_res_client_id_value_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_res_resource_id_spec_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_res_resource_id_spec_t)
 */
void
xcb_res_resource_id_spec_next (xcb_res_resource_id_spec_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_res_resource_id_spec_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_res_resource_id_spec_end (xcb_res_resource_id_spec_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_res_resource_size_spec_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_res_resource_size_spec_t)
 */
void
xcb_res_resource_size_spec_next (xcb_res_resource_size_spec_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_res_resource_size_spec_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_res_resource_size_spec_end (xcb_res_resource_size_spec_iterator_t i);

int
xcb_res_resource_size_value_sizeof (const void  *_buffer);

xcb_res_resource_size_spec_t *
xcb_res_resource_size_value_cross_references (const xcb_res_resource_size_value_t *R);

int
xcb_res_resource_size_value_cross_references_length (const xcb_res_resource_size_value_t *R);

xcb_res_resource_size_spec_iterator_t
xcb_res_resource_size_value_cross_references_iterator (const xcb_res_resource_size_value_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_res_resource_size_value_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_res_resource_size_value_t)
 */
void
xcb_res_resource_size_value_next (xcb_res_resource_size_value_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_res_resource_size_value_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_res_resource_size_value_end (xcb_res_resource_size_value_iterator_t i);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_res_query_version_cookie_t
xcb_res_query_version (xcb_connection_t *c,
                       uint8_t           client_major,
                       uint8_t           client_minor);

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
xcb_res_query_version_cookie_t
xcb_res_query_version_unchecked (xcb_connection_t *c,
                                 uint8_t           client_major,
                                 uint8_t           client_minor);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_res_query_version_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_res_query_version_reply_t *
xcb_res_query_version_reply (xcb_connection_t                *c,
                             xcb_res_query_version_cookie_t   cookie  /**< */,
                             xcb_generic_error_t            **e);

int
xcb_res_query_clients_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_res_query_clients_cookie_t
xcb_res_query_clients (xcb_connection_t *c);

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
xcb_res_query_clients_cookie_t
xcb_res_query_clients_unchecked (xcb_connection_t *c);

xcb_res_client_t *
xcb_res_query_clients_clients (const xcb_res_query_clients_reply_t *R);

int
xcb_res_query_clients_clients_length (const xcb_res_query_clients_reply_t *R);

xcb_res_client_iterator_t
xcb_res_query_clients_clients_iterator (const xcb_res_query_clients_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_res_query_clients_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_res_query_clients_reply_t *
xcb_res_query_clients_reply (xcb_connection_t                *c,
                             xcb_res_query_clients_cookie_t   cookie  /**< */,
                             xcb_generic_error_t            **e);

int
xcb_res_query_client_resources_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_res_query_client_resources_cookie_t
xcb_res_query_client_resources (xcb_connection_t *c,
                                uint32_t          xid);

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
xcb_res_query_client_resources_cookie_t
xcb_res_query_client_resources_unchecked (xcb_connection_t *c,
                                          uint32_t          xid);

xcb_res_type_t *
xcb_res_query_client_resources_types (const xcb_res_query_client_resources_reply_t *R);

int
xcb_res_query_client_resources_types_length (const xcb_res_query_client_resources_reply_t *R);

xcb_res_type_iterator_t
xcb_res_query_client_resources_types_iterator (const xcb_res_query_client_resources_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_res_query_client_resources_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_res_query_client_resources_reply_t *
xcb_res_query_client_resources_reply (xcb_connection_t                         *c,
                                      xcb_res_query_client_resources_cookie_t   cookie  /**< */,
                                      xcb_generic_error_t                     **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_res_query_client_pixmap_bytes_cookie_t
xcb_res_query_client_pixmap_bytes (xcb_connection_t *c,
                                   uint32_t          xid);

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
xcb_res_query_client_pixmap_bytes_cookie_t
xcb_res_query_client_pixmap_bytes_unchecked (xcb_connection_t *c,
                                             uint32_t          xid);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_res_query_client_pixmap_bytes_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_res_query_client_pixmap_bytes_reply_t *
xcb_res_query_client_pixmap_bytes_reply (xcb_connection_t                            *c,
                                         xcb_res_query_client_pixmap_bytes_cookie_t   cookie  /**< */,
                                         xcb_generic_error_t                        **e);

int
xcb_res_query_client_ids_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_res_query_client_ids_cookie_t
xcb_res_query_client_ids (xcb_connection_t               *c,
                          uint32_t                        num_specs,
                          const xcb_res_client_id_spec_t *specs);

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
xcb_res_query_client_ids_cookie_t
xcb_res_query_client_ids_unchecked (xcb_connection_t               *c,
                                    uint32_t                        num_specs,
                                    const xcb_res_client_id_spec_t *specs);

int
xcb_res_query_client_ids_ids_length (const xcb_res_query_client_ids_reply_t *R);

xcb_res_client_id_value_iterator_t
xcb_res_query_client_ids_ids_iterator (const xcb_res_query_client_ids_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_res_query_client_ids_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_res_query_client_ids_reply_t *
xcb_res_query_client_ids_reply (xcb_connection_t                   *c,
                                xcb_res_query_client_ids_cookie_t   cookie  /**< */,
                                xcb_generic_error_t               **e);

int
xcb_res_query_resource_bytes_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_res_query_resource_bytes_cookie_t
xcb_res_query_resource_bytes (xcb_connection_t                 *c,
                              uint32_t                          client,
                              uint32_t                          num_specs,
                              const xcb_res_resource_id_spec_t *specs);

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
xcb_res_query_resource_bytes_cookie_t
xcb_res_query_resource_bytes_unchecked (xcb_connection_t                 *c,
                                        uint32_t                          client,
                                        uint32_t                          num_specs,
                                        const xcb_res_resource_id_spec_t *specs);

int
xcb_res_query_resource_bytes_sizes_length (const xcb_res_query_resource_bytes_reply_t *R);

xcb_res_resource_size_value_iterator_t
xcb_res_query_resource_bytes_sizes_iterator (const xcb_res_query_resource_bytes_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_res_query_resource_bytes_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_res_query_resource_bytes_reply_t *
xcb_res_query_resource_bytes_reply (xcb_connection_t                       *c,
                                    xcb_res_query_resource_bytes_cookie_t   cookie  /**< */,
                                    xcb_generic_error_t                   **e);


#ifdef __cplusplus
}
#endif

#endif

/**
 * @}
 */
