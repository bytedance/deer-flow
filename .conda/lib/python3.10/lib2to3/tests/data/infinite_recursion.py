# Verify that 2to3 falls back from the recursive pattern matching scheme to a
# slower, iterative scheme in the event of a RecursionError.
from ctypes import *
STRING = c_char_p


OSUnknownByteOrder = 0
UIT_PROMPT = 1
P_PGID = 2
P_PID = 1
UIT_ERROR = 5
UIT_INFO = 4
UIT_NONE = 0
P_ALL = 0
UIT_VERIFY = 2
OSBigEndian = 2
UIT_BOOLEAN = 3
OSLittleEndian = 1
__darwin_nl_item = c_int
__darwin_wctrans_t = c_int
__darwin_wctype_t = c_ulong
__int8_t = c_byte
__uint8_t = c_ubyte
__int16_t = c_short
__uint16_t = c_ushort
__int32_t = c_int
__uint32_t = c_uint
__int64_t = c_longlong
__uint64_t = c_ulonglong
__darwin_intptr_t = c_long
__darwin_natural_t = c_uint
__darwin_ct_rune_t = c_int
class __mbstate_t(Union):
    pass
__mbstate_t._pack_ = 4
__mbstate_t._fields_ = [
    ('__mbstate8', c_char * 128),
    ('_mbstateL', c_longlong),
]
assert sizeof(__mbstate_t) == 128, sizeof(__mbstate_t)
assert alignment(__mbstate_t) == 4, alignment(__mbstate_t)
__darwin_mbstate_t = __mbstate_t
__darwin_ptrdiff_t = c_int
__darwin_size_t = c_ulong
__darwin_va_list = STRING
__darwin_wchar_t = c_int
__darwin_rune_t = __darwin_wchar_t
__darwin_wint_t = c_int
__darwin_clock_t = c_ulong
__darwin_socklen_t = __uint32_t
__darwin_ssize_t = c_long
__darwin_time_t = c_long
sig_atomic_t = c_int
class sigcontext(Structure):
    pass
sigcontext._fields_ = [
    ('sc_onstack', c_int),
    ('sc_mask', c_int),
    ('sc_eax', c_uint),
    ('sc_ebx', c_uint),
    ('sc_ecx', c_uint),
    ('sc_edx', c_uint),
    ('sc_edi', c_uint),
    ('sc_esi', c_uint),
    ('sc_ebp', c_uint),
    ('sc_esp', c_uint),
    ('sc_ss', c_uint),
    ('sc_eflags', c_uint),
    ('sc_eip', c_uint),
    ('sc_cs', c_uint),
    ('sc_ds', c_uint),
    ('sc_es', c_uint),
    ('sc_fs', c_uint),
    ('sc_gs', c_uint),
]
assert sizeof(sigcontext) == 72, sizeof(sigcontext)
assert alignment(sigcontext) == 4, alignment(sigcontext)
u_int8_t = c_ubyte
u_int16_t = c_ushort
u_int32_t = c_uint
u_int64_t = c_ulonglong
int32_t = c_int
register_t = int32_t
user_addr_t = u_int64_t
user_size_t = u_int64_t
int64_t = c_longlong
user_ssize_t = int64_t
user_long_t = int64_t
user_ulong_t = u_int64_t
user_time_t = int64_t
syscall_arg_t = u_int64_t

# values for unnamed enumeration
class aes_key_st(Structure):
    pass
aes_key_st._fields_ = [
    ('rd_key', c_ulong * 60),
    ('rounds', c_int),
]
assert sizeof(aes_key_st) == 244, sizeof(aes_key_st)
assert alignment(aes_key_st) == 4, alignment(aes_key_st)
AES_KEY = aes_key_st
class asn1_ctx_st(Structure):
    pass
asn1_ctx_st._fields_ = [
    ('p', POINTER(c_ubyte)),
    ('eos', c_int),
    ('error', c_int),
    ('inf', c_int),
    ('tag', c_int),
    ('xclass', c_int),
    ('slen', c_long),
    ('max', POINTER(c_ubyte)),
    ('q', POINTER(c_ubyte)),
    ('pp', POINTER(POINTER(c_ubyte))),
    ('line', c_int),
]
assert sizeof(asn1_ctx_st) == 44, sizeof(asn1_ctx_st)
assert alignment(asn1_ctx_st) == 4, alignment(asn1_ctx_st)
ASN1_CTX = asn1_ctx_st
class asn1_object_st(Structure):
    pass
asn1_object_st._fields_ = [
    ('sn', STRING),
    ('ln', STRING),
    ('nid', c_int),
    ('length', c_int),
    ('data', POINTER(c_ubyte)),
    ('flags', c_int),
]
assert sizeof(asn1_object_st) == 24, sizeof(asn1_object_st)
assert alignment(asn1_object_st) == 4, alignment(asn1_object_st)
ASN1_OBJECT = asn1_object_st
class asn1_string_st(Structure):
    pass
asn1_string_st._fields_ = [
    ('length', c_int),
    ('type', c_int),
    ('data', POINTER(c_ubyte)),
    ('flags', c_long),
]
assert sizeof(asn1_string_st) == 16, sizeof(asn1_string_st)
assert alignment(asn1_string_st) == 4, alignment(asn1_string_st)
ASN1_STRING = asn1_string_st
class ASN1_ENCODING_st(Structure):
    pass
ASN1_ENCODING_st._fields_ = [
    ('enc', POINTER(c_ubyte)),
    ('len', c_long),
    ('modified', c_int),
]
assert sizeof(ASN1_ENCODING_st) == 12, sizeof(ASN1_ENCODING_st)
assert alignment(ASN1_ENCODING_st) == 4, alignment(ASN1_ENCODING_st)
ASN1_ENCODING = ASN1_ENCODING_st
class asn1_string_table_st(Structure):
    pass
asn1_string_table_st._fields_ = [
    ('nid', c_int),
    ('minsize', c_long),
    ('maxsize', c_long),
    ('mask', c_ulong),
    ('flags', c_ulong),
]
assert sizeof(asn1_string_table_st) == 20, sizeof(asn1_string_table_st)
assert alignment(asn1_string_table_st) == 4, alignment(asn1_string_table_st)
ASN1_STRING_TABLE = asn1_string_table_st
class ASN1_TEMPLATE_st(Structure):
    pass
ASN1_TEMPLATE_st._fields_ = [
]
ASN1_TEMPLATE = ASN1_TEMPLATE_st
class ASN1_ITEM_st(Structure):
    pass
ASN1_ITEM = ASN1_ITEM_st
ASN1_ITEM_st._fields_ = [
]
class ASN1_TLC_st(Structure):
    pass
ASN1_TLC = ASN1_TLC_st
ASN1_TLC_st._fields_ = [
]
class ASN1_VALUE_st(Structure):
    pass
ASN1_VALUE_st._fields_ = [
]
ASN1_VALUE = ASN1_VALUE_st
ASN1_ITEM_EXP = ASN1_ITEM
class asn1_type_st(Structure):
    pass
class N12asn1_type_st4DOLLAR_11E(Union):
    pass
ASN1_BOOLEAN = c_int
ASN1_INTEGER = asn1_string_st
ASN1_ENUMERATED = asn1_string_st
ASN1_BIT_STRING = asn1_string_st
ASN1_OCTET_STRING = asn1_string_st
ASN1_PRINTABLESTRING = asn1_string_st
ASN1_T61STRING = asn1_string_st
ASN1_IA5STRING = asn1_string_st
ASN1_GENERALSTRING = asn1_string_st
ASN1_BMPSTRING = asn1_string_st
ASN1_UNIVERSALSTRING = asn1_string_st
ASN1_UTCTIME = asn1_string_st
ASN1_GENERALIZEDTIME = asn1_string_st
ASN1_VISIBLESTRING = asn1_string_st
ASN1_UTF8STRING = asn1_string_st
N12asn1_type_st4DOLLAR_11E._fields_ = [
    ('ptr', STRING),
    ('boolean', ASN1_BOOLEAN),
    ('asn1_string', POINTER(ASN1_STRING)),
    ('object', POINTER(ASN1_OBJECT)),
    ('integer', POINTER(ASN1_INTEGER)),
    ('enumerated', POINTER(ASN1_ENUMERATED)),
    ('bit_string', POINTER(ASN1_BIT_STRING)),
    ('octet_string', POINTER(ASN1_OCTET_STRING)),
    ('printablestring', POINTER(ASN1_PRINTABLESTRING)),
    ('t61string', POINTER(ASN1_T61STRING)),
    ('ia5string', POINTER(ASN1_IA5STRING)),
    ('generalstring', POINTER(ASN1_GENERALSTRING)),
    ('bmpstring', POINTER(ASN1_BMPSTRING)),
    ('universalstring', POINTER(ASN1_UNIVERSALSTRING)),
    ('utctime', POINTER(ASN1_UTCTIME)),
    ('generalizedtime', POINTER(ASN1_GENERALIZEDTIME)),
    ('visiblestring', POINTER(ASN1_VISIBLESTRING)),
    ('utf8string', POINTER(ASN1_UTF8STRING)),
    ('set', POINTER(ASN1_STRING)),
    ('sequence', POINTER(ASN1_STRING)),
]
assert sizeof(N12asn1_type_st4DOLLAR_11E) == 4, sizeof(N12asn1_type_st4DOLLAR_11E)
assert alignment(N12asn1_type_st4DOLLAR_11E) == 4, alignment(N12asn1_type_st4DOLLAR_11E)
asn1_type_st._fields_ = [
    ('type', c_int),
    ('value', N12asn1_type_st4DOLLAR_11E),
]
assert sizeof(asn1_type_st) == 8, sizeof(asn1_type_st)
assert alignment(asn1_type_st) == 4, alignment(asn1_type_st)
ASN1_TYPE = asn1_type_st
class asn1_method_st(Structure):
    pass
asn1_method_st._fields_ = [
    ('i2d', CFUNCTYPE(c_int)),
    ('d2i', CFUNCTYPE(STRING)),
    ('create', CFUNCTYPE(STRING)),
    ('destroy', CFUNCTYPE(None)),
]
assert sizeof(asn1_method_st) == 16, sizeof(asn1_method_st)
assert alignment(asn1_method_st) == 4, alignment(asn1_method_st)
ASN1_METHOD = asn1_method_st
class asn1_header_st(Structure):
    pass
asn1_header_st._fields_ = [
    ('header', POINTER(ASN1_OCTET_STRING)),
    ('data', STRING),
    ('meth', POINTER(ASN1_METHOD)),
]
assert sizeof(asn1_header_st) == 12, sizeof(asn1_header_st)
assert alignment(asn1_header_st) == 4, alignment(asn1_header_st)
ASN1_HEADER = asn1_header_st
class BIT_STRING_BITNAME_st(Structure):
    pass
BIT_STRING_BITNAME_st._fields_ = [
    ('bitnum', c_int),
    ('lname', STRING),
    ('sname', STRING),
]
assert sizeof(BIT_STRING_BITNAME_st) == 12, sizeof(BIT_STRING_BITNAME_st)
assert alignment(BIT_STRING_BITNAME_st) == 4, alignment(BIT_STRING_BITNAME_st)
BIT_STRING_BITNAME = BIT_STRING_BITNAME_st
class bio_st(Structure):
    pass
BIO = bio_st
bio_info_cb = CFUNCTYPE(None, POINTER(bio_st), c_int, STRING, c_int, c_long, c_long)
class bio_method_st(Structure):
    pass
bio_method_st._fields_ = [
    ('type', c_int),
    ('name', STRING),
    ('bwrite', CFUNCTYPE(c_int, POINTER(BIO), STRING, c_int)),
    ('bread', CFUNCTYPE(c_int, POINTER(BIO), STRING, c_int)),
    ('bputs', CFUNCTYPE(c_int, POINTER(BIO), STRING)),
    ('bgets', CFUNCTYPE(c_int, POINTER(BIO), STRING, c_int)),
    ('ctrl', CFUNCTYPE(c_long, POINTER(BIO), c_int, c_long, c_void_p)),
    ('create', CFUNCTYPE(c_int, POINTER(BIO))),
    ('destroy', CFUNCTYPE(c_int, POINTER(BIO))),
    ('callback_ctrl', CFUNCTYPE(c_long, POINTER(BIO), c_int, POINTER(bio_info_cb))),
]
assert sizeof(bio_method_st) == 40, sizeof(bio_method_st)
assert alignment(bio_method_st) == 4, alignment(bio_method_st)
BIO_METHOD = bio_method_st
class crypto_ex_data_st(Structure):
    pass
class stack_st(Structure):
    pass
STACK = stack_st
crypto_ex_data_st._fields_ = [
    ('sk', POINTER(STACK)),
    ('dummy', c_int),
]
assert sizeof(crypto_ex_data_st) == 8, sizeof(crypto_ex_data_st)
assert alignment(crypto_ex_data_st) == 4, alignment(crypto_ex_data_st)
CRYPTO_EX_DATA = crypto_ex_data_st
bio_st._fields_ = [
    ('method', POINTER(BIO_METHOD)),
    ('callback', CFUNCTYPE(c_long, POINTER(bio_st), c_int, STRING, c_int, c_long, c_long)),
    ('cb_arg', STRING),
    ('init', c_int),
    ('shutdown', c_int),
    ('flags', c_int),
    ('retry_reason', c_int),
    ('num', c_int),
    ('ptr', c_void_p),
    ('next_bio', POINTER(bio_st)),
    ('prev_bio', POINTER(bio_st)),
    ('references', c_int),
    ('num_read', c_ulong),
    ('num_write', c_ulong),
    ('ex_data', CRYPTO_EX_DATA),
]
assert sizeof(bio_st) == 64, sizeof(bio_st)
assert alignment(bio_st) == 4, alignment(bio_st)
class bio_f_buffer_ctx_struct(Structure):
    pass
bio_f_buffer_ctx_struct._fields_ = [
    ('ibuf_size', c_int),
    ('obuf_size', c_int),
    ('ibuf', STRING),
    ('ibuf_len', c_int),
    ('ibuf_off', c_int),
    ('obuf', STRING),
    ('obuf_len', c_int),
    ('obuf_off', c_int),
]
assert sizeof(bio_f_buffer_ctx_struct) == 32, sizeof(bio_f_buffer_ctx_struct)
assert alignment(bio_f_buffer_ctx_struct) == 4, alignment(bio_f_buffer_ctx_struct)
BIO_F_BUFFER_CTX = bio_f_buffer_ctx_struct
class hostent(Structure):
    pass
hostent._fields_ = [
]
class bf_key_st(Structure):
    pass
bf_key_st._fields_ = [
    ('P', c_uint * 18),
    ('S', c_uint * 1024),
]
assert sizeof(bf_key_st) == 4168, sizeof(bf_key_st)
assert alignment(bf_key_st) == 4, alignment(bf_key_st)
BF_KEY = bf_key_st
class bignum_st(Structure):
    pass
bignum_st._fields_ = [
    ('d', POINTER(c_ulong)),
    ('top', c_int),
    ('dmax', c_int),
    ('neg', c_int),
    ('flags', c_int),
]
assert sizeof(bignum_st) == 20, sizeof(bignum_st)
assert alignment(bignum_st) == 4, alignment(bignum_st)
BIGNUM = bignum_st
class bignum_ctx(Structure):
    pass
bignum_ctx._fields_ = [
]
BN_CTX = bignum_ctx
class bn_blinding_st(Structure):
    pass
bn_blinding_st._fields_ = [
    ('init', c_int),
    ('A', POINTER(BIGNUM)),
    ('Ai', POINTER(BIGNUM)),
    ('mod', POINTER(BIGNUM)),
    ('thread_id', c_ulong),
]
assert sizeof(bn_blinding_st) == 20, sizeof(bn_blinding_st)
assert alignment(bn_blinding_st) == 4, alignment(bn_blinding_st)
BN_BLINDING = bn_blinding_st
class bn_mont_ctx_st(Structure):
    pass
bn_mont_ctx_st._fields_ = [
    ('ri', c_int),
    ('RR', BIGNUM),
    ('N', BIGNUM),
    ('Ni', BIGNUM),
    ('n0', c_ulong),
    ('flags', c_int),
]
assert sizeof(bn_mont_ctx_st) == 72, sizeof(bn_mont_ctx_st)
assert alignment(bn_mont_ctx_st) == 4, alignment(bn_mont_ctx_st)
BN_MONT_CTX = bn_mont_ctx_st
class bn_recp_ctx_st(Structure):
    pass
bn_recp_ctx_st._fields_ = [
    ('N', BIGNUM),
    ('Nr', BIGNUM),
    ('num_bits', c_int),
    ('shift', c_int),
    ('flags', c_int),
]
assert sizeof(bn_recp_ctx_st) == 52, sizeof(bn_recp_ctx_st)
assert alignment(bn_recp_ctx_st) == 4, alignment(bn_recp_ctx_st)
BN_RECP_CTX = bn_recp_ctx_st
class buf_mem_st(Structure):
    pass
buf_mem_st._fields_ = [
    ('length', c_int),
    ('data', STRING),
    ('max', c_int),
]
assert sizeof(buf_mem_st) == 12, sizeof(buf_mem_st)
assert alignment(buf_mem_st) == 4, alignment(buf_mem_st)
BUF_MEM = buf_mem_st
class cast_key_st(Structure):
    pass
cast_key_st._fields_ = [
    ('data', c_ulong * 32),
    ('short_key', c_int),
]
assert sizeof(cast_key_st) == 132, sizeof(cast_key_st)
assert alignment(cast_key_st) == 4, alignment(cast_key_st)
CAST_KEY = cast_key_st
class comp_method_st(Structure):
    pass
comp_method_st._fields_ = [
    ('type', c_int),
    ('name', STRING),
    ('init', CFUNCTYPE(c_int)),
    ('finish', CFUNCTYPE(None)),
    ('compress', CFUNCTYPE(c_int)),
    ('expand', CFUNCTYPE(c_int)),
    ('ctrl', CFUNCTYPE(c_long)),
    ('callback_ctrl', CFUNCTYPE(c_long)),
]
assert sizeof(comp_method_st) == 32, sizeof(comp_method_st)
assert alignment(comp_method_st) == 4, alignment(comp_method_st)
COMP_METHOD = comp_method_st
class comp_ctx_st(Structure):
    pass
comp_ctx_st._fields_ = [
    ('meth', POINTER(COMP_METHOD)),
    ('compress_in', c_ulong),
    ('compress_out', c_ulong),
    ('expand_in', c_ulong),
    ('expand_out', c_ulong),
    ('ex_data', CRYPTO_EX_DATA),
]
assert sizeof(comp_ctx_st) == 28, sizeof(comp_ctx_st)
assert alignment(comp_ctx_st) == 4, alignment(comp_ctx_st)
COMP_CTX = comp_ctx_st
class CRYPTO_dynlock_value(Structure):
    pass
CRYPTO_dynlock_value._fields_ = [
]
class CRYPTO_dynlock(Structure):
    pass
CRYPTO_dynlock._fields_ = [
    ('references', c_int),
    ('data', POINTER(CRYPTO_dynlock_value)),
]
assert sizeof(CRYPTO_dynlock) == 8, sizeof(CRYPTO_dynlock)
assert alignment(CRYPTO_dynlock) == 4, alignment(CRYPTO_dynlock)
BIO_dummy = bio_st
CRYPTO_EX_new = CFUNCTYPE(c_int, c_void_p, c_void_p, POINTER(CRYPTO_EX_DATA), c_int, c_long, c_void_p)
CRYPTO_EX_free = CFUNCTYPE(None, c_void_p, c_void_p, POINTER(CRYPTO_EX_DATA), c_int, c_long, c_void_p)
CRYPTO_EX_dup = CFUNCTYPE(c_int, POINTER(CRYPTO_EX_DATA), POINTER(CRYPTO_EX_DATA), c_void_p, c_int, c_long, c_void_p)
class crypto_ex_data_func_st(Structure):
    pass
crypto_ex_data_func_st._fields_ = [
    ('argl', c_long),
    ('argp', c_void_p),
    ('new_func', POINTER(CRYPTO_EX_new)),
    ('free_func', POINTER(CRYPTO_EX_free)),
    ('dup_func', POINTER(CRYPTO_EX_dup)),
]
assert sizeof(crypto_ex_data_func_st) == 20, sizeof(crypto_ex_data_func_st)
assert alignment(crypto_ex_data_func_st) == 4, alignment(crypto_ex_data_func_st)
CRYPTO_EX_DATA_FUNCS = crypto_ex_data_func_st
class st_CRYPTO_EX_DATA_IMPL(Structure):
    pass
CRYPTO_EX_DATA_IMPL = st_CRYPTO_EX_DATA_IMPL
st_CRYPTO_EX_DATA_IMPL._fields_ = [
]
CRYPTO_MEM_LEAK_CB = CFUNCTYPE(c_void_p, c_ulong, STRING, c_int, c_int, c_void_p)
DES_cblock = c_ubyte * 8
const_DES_cblock = c_ubyte * 8
class DES_ks(Structure):
    pass
class N6DES_ks3DOLLAR_9E(Union):
    pass
N6DES_ks3DOLLAR_9E._fields_ = [
    ('cblock', DES_cblock),
    ('deslong', c_ulong * 2),
]
assert sizeof(N6DES_ks3DOLLAR_9E) == 8, sizeof(N6DES_ks3DOLLAR_9E)
assert alignment(N6DES_ks3DOLLAR_9E) == 4, alignment(N6DES_ks3DOLLAR_9E)
DES_ks._fields_ = [
    ('ks', N6DES_ks3DOLLAR_9E * 16),
]
assert sizeof(DES_ks) == 128, sizeof(DES_ks)
assert alignment(DES_ks) == 4, alignment(DES_ks)
DES_key_schedule = DES_ks
_ossl_old_des_cblock = c_ubyte * 8
class _ossl_old_des_ks_struct(Structure):
    pass
class N23_ossl_old_des_ks_struct4DOLLAR_10E(Union):
    pass
N23_ossl_old_des_ks_struct4DOLLAR_10E._fields_ = [
    ('_', _ossl_old_des_cblock),
    ('pad', c_ulong * 2),
]
assert sizeof(N23_ossl_old_des_ks_struct4DOLLAR_10E) == 8, sizeof(N23_ossl_old_des_ks_struct4DOLLAR_10E)
assert alignment(N23_ossl_old_des_ks_struct4DOLLAR_10E) == 4, alignment(N23_ossl_old_des_ks_struct4DOLLAR_10E)
_ossl_old_des_ks_struct._fields_ = [
    ('ks', N23_ossl_old_des_ks_struct4DOLLAR_10E),
]
assert sizeof(_ossl_old_des_ks_struct) == 8, sizeof(_ossl_old_des_ks_struct)
assert alignment(_ossl_old_des_ks_struct) == 4, alignment(_ossl_old_des_ks_struct)
_ossl_old_des_key_schedule = _ossl_old_des_ks_struct * 16
class dh_st(Structure):
    pass
DH = dh_st
class dh_method(Structure):
    pass
dh_method._fields_ = [
    ('name', STRING),
    ('generate_key', CFUNCTYPE(c_int, POINTER(DH))),
    ('compute_key', CFUNCTYPE(c_int, POINTER(c_ubyte), POINTER(BIGNUM), POINTER(DH))),
    ('bn_mod_exp', CFUNCTYPE(c_int, POINTER(DH), POINTER(BIGNUM), POINTER(BIGNUM), POINTER(BIGNUM), POINTER(BIGNUM), POINTER(BN_CTX), POINTER(BN_MONT_CTX))),
    ('init', CFUNCTYPE(c_int, POINTER(DH))),
    ('finish', CFUNCTYPE(c_int, POINTER(DH))),
    ('flags', c_int),
    ('app_data', STRING),
]
assert sizeof(dh_method) == 32, sizeof(dh_method)
assert alignment(dh_method) == 4, alignment(dh_method)
DH_METHOD = dh_method
class engine_st(Structure):
    pass
ENGINE = engine_st
dh_st._fields_ = [
    ('pad', c_int),
    ('version', c_int),
    ('p', POINTER(BIGNUM)),
    ('g', POINTER(BIGNUM)),
    ('length', c_long),
    ('pub_key', POINTER(BIGNUM)),
    ('priv_key', POINTER(BIGNUM)),
    ('flags', c_int),
    ('method_mont_p', STRING),
    ('q', POINTER(BIGNUM)),
    ('j', POINTER(BIGNUM)),
    ('seed', POINTER(c_ubyte)),
    ('seedlen', c_int),
    ('counter', POINTER(BIGNUM)),
    ('references', c_int),
    ('ex_data', CRYPTO_EX_DATA),
    ('meth', POINTER(DH_METHOD)),
    ('engine', POINTER(ENGINE)),
]
assert sizeof(dh_st) == 76, sizeof(dh_st)
assert alignment(dh_st) == 4, alignment(dh_st)
class dsa_st(Structure):
    pass
DSA = dsa_st
class DSA_SIG_st(Structure):
    pass
DSA_SIG_st._fields_ = [
    ('r', POINTER(BIGNUM)),
    ('s', POINTER(BIGNUM)),
]
assert sizeof(DSA_SIG_st) == 8, sizeof(DSA_SIG_st)
assert alignment(DSA_SIG_st) == 4, alignment(DSA_SIG_st)
DSA_SIG = DSA_SIG_st
class dsa_method(Structure):
    pass
dsa_method._fields_ = [
    ('name', STRING),
    ('dsa_do_sign', CFUNCTYPE(POINTER(DSA_SIG), POINTER(c_ubyte), c_int, POINTER(DSA))),
    ('dsa_sign_setup', CFUNCTYPE(c_int, POINTER(DSA), POINTER(BN_CTX), POINTER(POINTER(BIGNUM)), POINTER(POINTER(BIGNUM)))),
    ('dsa_do_verify', CFUNCTYPE(c_int, POINTER(c_ubyte), c_int, POINTER(DSA_SIG), POINTER(DSA))),
    ('dsa_mod_exp', CFUNCTYPE(c_int, POINTER(DSA), POINTER(BIGNUM), POINTER(BIGNUM), POINTER(BIGNUM), POINTER(BIGNUM), POINTER(BIGNUM), POINTER(BIGNUM), POINTER(BN_CTX), POINTER(BN_MONT_CTX))),
    ('bn_mod_exp', CFUNCTYPE(c_int, POINTER(DSA), POINTER(BIGNUM), POINTER(BIGNUM), POINTER(BIGNUM), POINTER(BIGNUM), POINTER(BN_CTX), POINTER(BN_MONT_CTX))),
    ('init', CFUNCTYPE(c_int, POINTER(DSA))),
    ('finish', CFUNCTYPE(c_int, POINTER(DSA))),
    ('flags', c_int),
    ('app_data', STRING),
]
assert sizeof(dsa_method) == 40, sizeof(dsa_method)
assert alignment(dsa_method) == 4, alignment(dsa_method)
DSA_METHOD = dsa_method
dsa_st._fields_ = [
    ('pad', c_int),
    ('version', c_long),
    ('write_params', c_int),
    ('p', POINTER(BIGNUM)),
    ('q', POINTER(BIGNUM)),
    ('g', POINTER(BIGNUM)),
    ('pub_key', POINTER(BIGNUM)),
    ('priv_key', POINTER(BIGNUM)),
    ('kinv', POINTER(BIGNUM)),
    ('r', POINTER(BIGNUM)),
    ('flags', c_int),
    ('method_mont_p', STRING),
    ('references', c_int),
    ('ex_data', CRYPTO_EX_DATA),
    ('meth', POINTER(DSA_METHOD)),
    ('engine', POINTER(ENGINE)),
]
assert sizeof(dsa_st) == 68, sizeof(dsa_st)
assert alignment(dsa_st) == 4, alignment(dsa_st)
class evp_pkey_st(Structure):
    pass
class N11evp_pkey_st4DOLLAR_12E(Union):
    pass
class rsa_st(Structure):
    pass
N11evp_pkey_st4DOLLAR_12E._fields_ = [
    ('ptr', STRING),
    ('rsa', POINTER(rsa_st)),
    ('dsa', POINTER(dsa_st)),
    ('dh', POINTER(dh_st)),
]
assert sizeof(N11evp_pkey_st4DOLLAR_12E) == 4, sizeof(N11evp_pkey_st4DOLLAR_12E)
assert alignment(N11evp_pkey_st4DOLLAR_12E) == 4, alignment(N11evp_pkey_st4DOLLAR_12E)
evp_pkey_st._fields_ = [
    ('type', c_int),
    ('save_type', c_int),
    ('references', c_int),
    ('pkey', N11evp_pkey_st4DOLLAR_12E),
    ('save_parameters', c_int),
    ('attributes', POINTER(STACK)),
]
assert sizeof(evp_pkey_st) == 24, sizeof(evp_pkey_st)
assert alignment(evp_pkey_st) == 4, alignment(evp_pkey_st)
class env_md_st(Structure):
    pass
class env_md_ctx_st(Structure):
    pass
EVP_MD_CTX = env_md_ctx_st
env_md_st._fields_ = [
    ('type', c_int),
    ('pkey_type', c_int),
    ('md_size', c_int),
    ('flags', c_ulong),
    ('init', CFUNCTYPE(c_int, POINTER(EVP_MD_CTX))),
    ('update', CFUNCTYPE(c_int, POINTER(EVP_MD_CTX), c_void_p, c_ulong)),
    ('final', CFUNCTYPE(c_int, POINTER(EVP_MD_CTX), POINTER(c_ubyte))),
    ('copy', CFUNCTYPE(c_int, POINTER(EVP_MD_CTX), POINTER(EVP_MD_CTX))),
    ('cleanup', CFUNCTYPE(c_int, POINTER(EVP_MD_CTX))),
    ('sign', CFUNCTYPE(c_int)),
    ('verify', CFUNCTYPE(c_int)),
    ('required_pkey_type', c_int * 5),
    ('block_size', c_int),
    ('ctx_size', c_int),
]
assert sizeof(env_md_st) == 72, sizeof(env_md_st)
assert alignment(env_md_st) == 4, alignment(env_md_st)
EVP_MD = env_md_st
env_md_ctx_st._fields_ = [
    ('digest', POINTER(EVP_MD)),
    ('engine', POINTER(ENGINE)),
    ('flags', c_ulong),
    ('md_data', c_void_p),
]
assert sizeof(env_md_ctx_st) == 16, sizeof(env_md_ctx_st)
assert alignment(env_md_ctx_st) == 4, alignment(env_md_ctx_st)
class evp_cipher_st(Structure):
    pass
class evp_cipher_ctx_st(Structure):
    pass
EVP_CIPHER_CTX = evp_cipher_ctx_st
evp_cipher_st._fields_ = [
    ('nid', c_int),
    ('block_size', c_int),
    ('key_len', c_int),
    ('iv_len', c_int),
    ('flags', c_ulong),
    ('init', CFUNCTYPE(c_int, POINTER(EVP_CIPHER_CTX), POINTER(c_ubyte), POINTER(c_ubyte), c_int)),
    ('do_cipher', CFUNCTYPE(c_int, POINTER(EVP_CIPHER_CTX), POINTER(c_ubyte), POINTER(c_ubyte), c_uint)),
    ('cleanup', CFUNCTYPE(c_int, POINTER(EVP_CIPHER_CTX))),
    ('ctx_size', c_int),
    ('set_asn1_parameters', CFUNCTYPE(c_int, POINTER(EVP_CIPHER_CTX), POINTER(ASN1_TYPE))),
    ('get_asn1_parameters', CFUNCTYPE(c_int, POINTER(EVP_CIPHER_CTX), POINTER(ASN1_TYPE))),
    ('ctrl', CFUNCTYPE(c_int, POINTER(EVP_CIPHER_CTX), c_int, c_int, c_void_p)),
    ('app_data', c_void_p),
]
assert sizeof(evp_cipher_st) == 52, sizeof(evp_cipher_st)
assert alignment(evp_cipher_st) == 4, alignment(evp_cipher_st)
class evp_cipher_info_st(Structure):
    pass
EVP_CIPHER = evp_cipher_st
evp_cipher_info_st._fields_ = [
    ('cipher', POINTER(EVP_CIPHER)),
    ('iv', c_ubyte * 16),
]
assert sizeof(evp_cipher_info_st) == 20, sizeof(evp_cipher_info_st)
assert alignment(evp_cipher_info_st) == 4, alignment(evp_cipher_info_st)
EVP_CIPHER_INFO = evp_cipher_info_st
evp_cipher_ctx_st._fields_ = [
    ('cipher', POINTER(EVP_CIPHER)),
    ('engine', POINTER(ENGINE)),
    ('encrypt', c_int),
    ('buf_len', c_int),
    ('oiv', c_ubyte * 16),
    ('iv', c_ubyte * 16),
    ('buf', c_ubyte * 32),
    ('num', c_int),
    ('app_data', c_void_p),
    ('key_len', c_int),
    ('flags', c_ulong),
    ('cipher_data', c_void_p),
    ('final_used', c_int),
    ('block_mask', c_int),
    ('final', c_ubyte * 32),
]
assert sizeof(evp_cipher_ctx_st) == 140, sizeof(evp_cipher_ctx_st)
assert alignment(evp_cipher_ctx_st) == 4, alignment(evp_cipher_ctx_st)
class evp_Encode_Ctx_st(Structure):
    pass
evp_Encode_Ctx_st._fields_ = [
    ('num', c_int),
    ('length', c_int),
    ('enc_data', c_ubyte * 80),
    ('line_num', c_int),
    ('expect_nl', c_int),
]
assert sizeof(evp_Encode_Ctx_st) == 96, sizeof(evp_Encode_Ctx_st)
assert alignment(evp_Encode_Ctx_st) == 4, alignment(evp_Encode_Ctx_st)
EVP_ENCODE_CTX = evp_Encode_Ctx_st
EVP_PBE_KEYGEN = CFUNCTYPE(c_int, POINTER(EVP_CIPHER_CTX), STRING, c_int, POINTER(ASN1_TYPE), POINTER(EVP_CIPHER), POINTER(EVP_MD), c_int)
class lhash_node_st(Structure):
    pass
lhash_node_st._fields_ = [
    ('data', c_void_p),
    ('next', POINTER(lhash_node_st)),
    ('hash', c_ulong),
]
assert sizeof(lhash_node_st) == 12, sizeof(lhash_node_st)
assert alignment(lhash_node_st) == 4, alignment(lhash_node_st)
LHASH_NODE = lhash_node_st
LHASH_COMP_FN_TYPE = CFUNCTYPE(c_int, c_void_p, c_void_p)
LHASH_HASH_FN_TYPE = CFUNCTYPE(c_ulong, c_void_p)
LHASH_DOALL_FN_TYPE = CFUNCTYPE(None, c_void_p)
LHASH_DOALL_ARG_FN_TYPE = CFUNCTYPE(None, c_void_p, c_void_p)
class lhash_st(Structure):
    pass
lhash_st._fields_ = [
    ('b', POINTER(POINTER(LHASH_NODE))),
    ('comp', LHASH_COMP_FN_TYPE),
    ('hash', LHASH_HASH_FN_TYPE),
    ('num_nodes', c_uint),
    ('num_alloc_nodes', c_uint),
    ('p', c_uint),
    ('pmax', c_uint),
    ('up_load', c_ulong),
    ('down_load', c_ulong),
    ('num_items', c_ulong),
    ('num_expands', c_ulong),
    ('num_expand_reallocs', c_ulong),
    ('num_contracts', c_ulong),
    ('num_contract_reallocs', c_ulong),
    ('num_hash_calls', c_ulong),
    ('num_comp_calls', c_ulong),
    ('num_insert', c_ulong),
    ('num_replace', c_ulong),
    ('num_delete', c_ulong),
    ('num_no_delete', c_ulong),
    ('num_retrieve', c_ulong),
    ('num_retrieve_miss', c_ulong),
    ('num_hash_comps', c_ulong),
    ('error', c_int),
]
assert sizeof(lhash_st) == 96, sizeof(lhash_st)
assert alignment(lhash_st) == 4, alignment(lhash_st)
LHASH = lhash_st
class MD2state_st(Structure):
    pass
MD2state_st._fields_ = [
    ('num', c_int),
    ('data', c_ubyte * 16),
    ('cksm', c_uint * 16),
    ('state', c_uint * 16),
]
assert sizeof(MD2state_st) == 148, sizeof(MD2state_st)
assert alignment(MD2state_st) == 4, alignment(MD2state_st)
MD2_CTX = MD2state_st
class MD4state_st(Structure):
    pass
MD4state_st._fields_ = [
    ('A', c_uint),
    ('B', c_uint),
    ('C', c_uint),
    ('D', c_uint),
    ('Nl', c_uint),
    ('Nh', c_uint),
    ('data', c_uint * 16),
    ('num', c_int),
]
assert sizeof(MD4state_st) == 92, sizeof(MD4state_st)
assert alignment(MD4state_st) == 4, alignment(MD4state_st)
MD4_CTX = MD4state_st
class MD5state_st(Structure):
    pass
MD5state_st._fields_ = [
    ('A', c_uint),
    ('B', c_uint),
    ('C', c_uint),
    ('D', c_uint),
    ('Nl', c_uint),
    ('Nh', c_uint),
    ('data', c_uint * 16),
    ('num', c_int),
]
assert sizeof(MD5state_st) == 92, sizeof(MD5state_st)
assert alignment(MD5state_st) == 4, alignment(MD5state_st)
MD5_CTX = MD5state_st
class mdc2_ctx_st(Structure):
    pass
mdc2_ctx_st._fields_ = [
    ('num', c_int),
    ('data', c_ubyte * 8),
    ('h', DES_cblock),
    ('hh', DES_cblock),
    ('pad_type', c_int),
]
assert sizeof(mdc2_ctx_st) == 32, sizeof(mdc2_ctx_st)
assert alignment(mdc2_ctx_st) == 4, alignment(mdc2_ctx_st)
MDC2_CTX = mdc2_ctx_st
class obj_name_st(Structure):
    pass
obj_name_st._fields_ = [
    ('type', c_int),
    ('alias', c_int),
    ('name', STRING),
    ('data', STRING),
]
assert sizeof(obj_name_st) == 16, sizeof(obj_name_st)
assert alignment(obj_name_st) == 4, alignment(obj_name_st)
OBJ_NAME = obj_name_st
ASN1_TIME = asn1_string_st
ASN1_NULL = c_int
EVP_PKEY = evp_pkey_st
class x509_st(Structure):
    pass
X509 = x509_st
class X509_algor_st(Structure):
    pass
X509_ALGOR = X509_algor_st
class X509_crl_st(Structure):
    pass
X509_CRL = X509_crl_st
class X509_name_st(Structure):
    pass
X509_NAME = X509_name_st
class x509_store_st(Structure):
    pass
X509_STORE = x509_store_st
class x509_store_ctx_st(Structure):
    pass
X509_STORE_CTX = x509_store_ctx_st
engine_st._fields_ = [
]
class PEM_Encode_Seal_st(Structure):
    pass
PEM_Encode_Seal_st._fields_ = [
    ('encode', EVP_ENCODE_CTX),
    ('md', EVP_MD_CTX),
    ('cipher', EVP_CIPHER_CTX),
]
assert sizeof(PEM_Encode_Seal_st) == 252, sizeof(PEM_Encode_Seal_st)
assert alignment(PEM_Encode_Seal_st) == 4, alignment(PEM_Encode_Seal_st)
PEM_ENCODE_SEAL_CTX = PEM_Encode_Seal_st
class pem_recip_st(Structure):
    pass
pem_recip_st._fields_ = [
    ('name', STRING),
    ('dn', POINTER(X509_NAME)),
    ('cipher', c_int),
    ('key_enc', c_int),
]
assert sizeof(pem_recip_st) == 16, sizeof(pem_recip_st)
assert alignment(pem_recip_st) == 4, alignment(pem_recip_st)
PEM_USER = pem_recip_st
class pem_ctx_st(Structure):
    pass
class N10pem_ctx_st4DOLLAR_16E(Structure):
    pass
N10pem_ctx_st4DOLLAR_16E._fields_ = [
    ('version', c_int),
    ('mode', c_int),
]
assert sizeof(N10pem_ctx_st4DOLLAR_16E) == 8, sizeof(N10pem_ctx_st4DOLLAR_16E)
assert alignment(N10pem_ctx_st4DOLLAR_16E) == 4, alignment(N10pem_ctx_st4DOLLAR_16E)
class N10pem_ctx_st4DOLLAR_17E(Structure):
    pass
N10pem_ctx_st4DOLLAR_17E._fields_ = [
    ('cipher', c_int),
]
assert sizeof(N10pem_ctx_st4DOLLAR_17E) == 4, sizeof(N10pem_ctx_st4DOLLAR_17E)
assert alignment(N10pem_ctx_st4DOLLAR_17E) == 4, alignment(N10pem_ctx_st4DOLLAR_17E)
pem_ctx_st._fields_ = [
    ('type', c_int),
    ('proc_type', N10pem_ctx_st4DOLLAR_16E),
    ('domain', STRING),
    ('DEK_info', N10pem_ctx_st4DOLLAR_17E),
    ('originator', POINTER(PEM_USER)),
    ('num_recipient', c_int),
    ('recipient', POINTER(POINTER(PEM_USER))),
    ('x509_chain', POINTER(STACK)),
    ('md', POINTER(EVP_MD)),
    ('md_enc', c_int),
    ('md_len', c_int),
    ('md_data', STRING),
    ('dec', POINTER(EVP_CIPHER)),
    ('key_len', c_int),
    ('key', POINTER(c_ubyte)),
    ('data_enc', c_int),
    ('data_len', c_int),
    ('data', POINTER(c_ubyte)),
]
assert sizeof(pem_ctx_st) == 76, sizeof(pem_ctx_st)
assert alignment(pem_ctx_st) == 4, alignment(pem_ctx_st)
PEM_CTX = pem_ctx_st
pem_password_cb = CFUNCTYPE(c_int, STRING, c_int, c_int, c_void_p)
class pkcs7_issuer_and_serial_st(Structure):
    pass
pkcs7_issuer_and_serial_st._fields_ = [
    ('issuer', POINTER(X509_NAME)),
    ('serial', POINTER(ASN1_INTEGER)),
]
assert sizeof(pkcs7_issuer_and_serial_st) == 8, sizeof(pkcs7_issuer_and_serial_st)
assert alignment(pkcs7_issuer_and_serial_st) == 4, alignment(pkcs7_issuer_and_serial_st)
PKCS7_ISSUER_AND_SERIAL = pkcs7_issuer_and_serial_st
class pkcs7_signer_info_st(Structure):
    pass
pkcs7_signer_info_st._fields_ = [
    ('version', POINTER(ASN1_INTEGER)),
    ('issuer_and_serial', POINTER(PKCS7_ISSUER_AND_SERIAL)),
    ('digest_alg', POINTER(X509_ALGOR)),
    ('auth_attr', POINTER(STACK)),
    ('digest_enc_alg', POINTER(X509_ALGOR)),
    ('enc_digest', POINTER(ASN1_OCTET_STRING)),
    ('unauth_attr', POINTER(STACK)),
    ('pkey', POINTER(EVP_PKEY)),
]
assert sizeof(pkcs7_signer_info_st) == 32, sizeof(pkcs7_signer_info_st)
assert alignment(pkcs7_signer_info_st) == 4, alignment(pkcs7_signer_info_st)
PKCS7_SIGNER_INFO = pkcs7_signer_info_st
class pkcs7_recip_info_st(Structure):
    pass
pkcs7_recip_info_st._fields_ = [
    ('version', POINTER(ASN1_INTEGER)),
    ('issuer_and_serial', POINTER(PKCS7_ISSUER_AND_SERIAL)),
    ('key_enc_algor', POINTER(X509_ALGOR)),
    ('enc_key', POINTER(ASN1_OCTET_STRING)),
    ('cert', POINTER(X509)),
]
assert sizeof(pkcs7_recip_info_st) == 20, sizeof(pkcs7_recip_info_st)
assert alignment(pkcs7_recip_info_st) == 4, alignment(pkcs7_recip_info_st)
PKCS7_RECIP_INFO = pkcs7_recip_info_st
class pkcs7_signed_st(Structure):
    pass
class pkcs7_st(Structure):
    pass
pkcs7_signed_st._fields_ = [
    ('version', POINTER(ASN1_INTEGER)),
    ('md_algs', POINTER(STACK)),
    ('cert', POINTER(STACK)),
    ('crl', POINTER(STACK)),
    ('signer_info', POINTER(STACK)),
    ('contents', POINTER(pkcs7_st)),
]
assert sizeof(pkcs7_signed_st) == 24, sizeof(pkcs7_signed_st)
assert alignment(pkcs7_signed_st) == 4, alignment(pkcs7_signed_st)
PKCS7_SIGNED = pkcs7_signed_st
class pkcs7_enc_content_st(Structure):
    pass
pkcs7_enc_content_st._fields_ = [
    ('content_type', POINTER(ASN1_OBJECT)),
    ('algorithm', POINTER(X509_ALGOR)),
    ('enc_data', POINTER(ASN1_OCTET_STRING)),
    ('cipher', POINTER(EVP_CIPHER)),
]
assert sizeof(pkcs7_enc_content_st) == 16, sizeof(pkcs7_enc_content_st)
assert alignment(pkcs7_enc_content_st) == 4, alignment(pkcs7_enc_content_st)
PKCS7_ENC_CONTENT = pkcs7_enc_content_st
class pkcs7_enveloped_st(Structure):
    pass
pkcs7_enveloped_st._fields_ = [
    ('version', POINTER(ASN1_INTEGER)),
    ('recipientinfo', POINTER(STACK)),
    ('enc_data', POINTER(PKCS7_ENC_CONTENT)),
]
assert sizeof(pkcs7_enveloped_st) == 12, sizeof(pkcs7_enveloped_st)
assert alignment(pkcs7_enveloped_st) == 4, alignment(pkcs7_enveloped_st)
PKCS7_ENVELOPE = pkcs7_enveloped_st
class pkcs7_signedandenveloped_st(Structure):
    pass
pkcs7_signedandenveloped_st._fields_ = [
    ('version', POINTER(ASN1_INTEGER)),
    ('md_algs', POINTER(STACK)),
    ('cert', POINTER(STACK)),
    ('crl', POINTER(STACK)),
    ('signer_info', POINTER(STACK)),
    ('enc_data', POINTER(PKCS7_ENC_CONTENT)),
    ('recipientinfo', POINTER(STACK)),
]
assert sizeof(pkcs7_signedandenveloped_st) == 28, sizeof(pkcs7_signedandenveloped_st)
assert alignment(pkcs7_signedandenveloped_st) == 4, alignment(pkcs7_signedandenveloped_st)
PKCS7_SIGN_ENVELOPE = pkcs7_signedandenveloped_st
class pkcs7_digest_st(Structure):
    pass
pkcs7_digest_st._fields_ = [
    ('version', POINTER(ASN1_INTEGER)),
    ('md', POINTER(X509_ALGOR)),
    ('contents', POINTER(pkcs7_st)),
    ('digest', POINTER(ASN1_OCTET_STRING)),
]
assert sizeof(pkcs7_digest_st) == 16, sizeof(pkcs7_digest_st)
assert alignment(pkcs7_digest_st) == 4, alignment(pkcs7_digest_st)
PKCS7_DIGEST = pkcs7_digest_st
class pkcs7_encrypted_st(Structure):
    pass
pkcs7_encrypted_st._fields_ = [
    ('version', POINTER(ASN1_INTEGER)),
    ('enc_data', POINTER(PKCS7_ENC_CONTENT)),
]
assert sizeof(pkcs7_encrypted_st) == 8, sizeof(pkcs7_encrypted_st)
assert alignment(pkcs7_encrypted_st) == 4, alignment(pkcs7_encrypted_st)
PKCS7_ENCRYPT = pkcs7_encrypted_st
class N8pkcs7_st4DOLLAR_15E(Union):
    pass
N8pkcs7_st4DOLLAR_15E._fields_ = [
    ('ptr', STRING),
    ('data', POINTER(ASN1_OCTET_STRING)),
    ('sign', POINTER(PKCS7_SIGNED)),
    ('enveloped', POINTER(PKCS7_ENVELOPE)),
    ('signed_and_enveloped', POINTER(PKCS7_SIGN_ENVELOPE)),
    ('digest', POINTER(PKCS7_DIGEST)),
    ('encrypted', POINTER(PKCS7_ENCRYPT)),
    ('other', POINTER(ASN1_TYPE)),
]
assert sizeof(N8pkcs7_st4DOLLAR_15E) == 4, sizeof(N8pkcs7_st4DOLLAR_15E)
assert alignment(N8pkcs7_st4DOLLAR_15E) == 4, alignment(N8pkcs7_st4DOLLAR_15E)
pkcs7_st._fields_ = [
    ('asn1', POINTER(c_ubyte)),
    ('length', c_long),
    ('state', c_int),
    ('detached', c_int),
    ('type', POINTER(ASN1_OBJECT)),
    ('d', N8pkcs7_st4DOLLAR_15E),
]
assert sizeof(pkcs7_st) == 24, sizeof(pkcs7_st)
assert alignment(pkcs7_st) == 4, alignment(pkcs7_st)
PKCS7 = pkcs7_st
class rc2_key_st(Structure):
    pass
rc2_key_st._fields_ = [
    ('data', c_uint * 64),
]
assert sizeof(rc2_key_st) == 256, sizeof(rc2_key_st)
assert alignment(rc2_key_st) == 4, alignment(rc2_key_st)
RC2_KEY = rc2_key_st
class rc4_key_st(Structure):
    pass
rc4_key_st._fields_ = [
    ('x', c_ubyte),
    ('y', c_ubyte),
    ('data', c_ubyte * 256),
]
assert sizeof(rc4_key_st) == 258, sizeof(rc4_key_st)
assert alignment(rc4_key_st) == 1, alignment(rc4_key_st)
RC4_KEY = rc4_key_st
class rc5_key_st(Structure):
    pass
rc5_key_st._fields_ = [
    ('rounds', c_int),
    ('data', c_ulong * 34),
]
assert sizeof(rc5_key_st) == 140, sizeof(rc5_key_st)
assert alignment(rc5_key_st) == 4, alignment(rc5_key_st)
RC5_32_KEY = rc5_key_st
class RIPEMD160state_st(Structure):
    pass
RIPEMD160state_st._fields_ = [
    ('A', c_uint),
    ('B', c_uint),
    ('C', c_uint),
    ('D', c_uint),
    ('E', c_uint),
    ('Nl', c_uint),
    ('Nh', c_uint),
    ('data', c_uint * 16),
    ('num', c_int),
]
assert sizeof(RIPEMD160state_st) == 96, sizeof(RIPEMD160state_st)
assert alignment(RIPEMD160state_st) == 4, alignment(RIPEMD160state_st)
RIPEMD160_CTX = RIPEMD160state_st
RSA = rsa_st
class rsa_meth_st(Structure):
    pass
rsa_meth_st._fields_ = [
    ('name', STRING),
    ('rsa_pub_enc', CFUNCTYPE(c_int, c_int, POINTER(c_ubyte), POINTER(c_ubyte), POINTER(RSA), c_int)),
    ('rsa_pub_dec', CFUNCTYPE(c_int, c_int, POINTER(c_ubyte), POINTER(c_ubyte), POINTER(RSA), c_int)),
    ('rsa_priv_enc', CFUNCTYPE(c_int, c_int, POINTER(c_ubyte), POINTER(c_ubyte), POINTER(RSA), c_int)),
    ('rsa_priv_dec', CFUNCTYPE(c_int, c_int, POINTER(c_ubyte), POINTER(c_ubyte), POINTER(RSA), c_int)),
    ('rsa_mod_exp', CFUNCTYPE(c_int, POINTER(BIGNUM), POINTER(BIGNUM), POINTER(RSA))),
    ('bn_mod_exp', CFUNCTYPE(c_int, POINTER(BIGNUM), POINTER(BIGNUM), POINTER(BIGNUM), POINTER(BIGNUM), POINTER(BN_CTX), POINTER(BN_MONT_CTX))),
    ('init', CFUNCTYPE(c_int, POINTER(RSA))),
    ('finish', CFUNCTYPE(c_int, POINTER(RSA))),
    ('flags', c_int),
    ('app_data', STRING),
    ('rsa_sign', CFUNCTYPE(c_int, c_int, POINTER(c_ubyte), c_uint, POINTER(c_ubyte), POINTER(c_uint), POINTER(RSA))),
    ('rsa_verify', CFUNCTYPE(c_int, c_int, POINTER(c_ubyte), c_uint, POINTER(c_ubyte), c_uint, POINTER(RSA))),
]
assert sizeof(rsa_meth_st) == 52, sizeof(rsa_meth_st)
assert alignment(rsa_meth_st) == 4, alignment(rsa_meth_st)
RSA_METHOD = rsa_meth_st
rsa_st._fields_ = [
    ('pad', c_int),
    ('version', c_long),
    ('meth', POINTER(RSA_METHOD)),
    ('engine', POINTER(ENGINE)),
    ('n', POINTER(BIGNUM)),
    ('e', POINTER(BIGNUM)),
    ('d', POINTER(BIGNUM)),
    ('p', POINTER(BIGNUM)),
    ('q', POINTER(BIGNUM)),
    ('dmp1', POINTER(BIGNUM)),
    ('dmq1', POINTER(BIGNUM)),
    ('iqmp', POINTER(BIGNUM)),
    ('ex_data', CRYPTO_EX_DATA),
    ('references', c_int),
    ('flags', c_int),
    ('_method_mod_n', POINTER(BN_MONT_CTX)),
    ('_method_mod_p', POINTER(BN_MONT_CTX)),
    ('_method_mod_q', POINTER(BN_MONT_CTX)),
    ('bignum_data', STRING),
    ('blinding', POINTER(BN_BLINDING)),
]
assert sizeof(rsa_st) == 84, sizeof(rsa_st)
assert alignment(rsa_st) == 4, alignment(rsa_st)
openssl_fptr = CFUNCTYPE(None)
class SHAstate_st(Structure):
    pass
SHAstate_st._fields_ = [
    ('h0', c_uint),
    ('h1', c_uint),
    ('h2', c_uint),
    ('h3', c_uint),
    ('h4', c_uint),
    ('Nl', c_uint),
    ('Nh', c_uint),
    ('data', c_uint * 16),
    ('num', c_int),
]
assert sizeof(SHAstate_st) == 96, sizeof(SHAstate_st)
assert alignment(SHAstate_st) == 4, alignment(SHAstate_st)
SHA_CTX = SHAstate_st
class ssl_st(Structure):
    pass
ssl_crock_st = POINTER(ssl_st)
class ssl_cipher_st(Structure):
    pass
ssl_cipher_st._fields_ = [
    ('valid', c_int),
    ('name', STRING),
    ('id', c_ulong),
    ('algorithms', c_ulong),
    ('algo_strength', c_ulong),
    ('algorithm2', c_ulong),
    ('strength_bits', c_int),
    ('alg_bits', c_int),
    ('mask', c_ulong),
    ('mask_strength', c_ulong),
]
assert sizeof(ssl_cipher_st) == 40, sizeof(ssl_cipher_st)
assert alignment(ssl_cipher_st) == 4, alignment(ssl_cipher_st)
SSL_CIPHER = ssl_cipher_st
SSL = ssl_st
class ssl_ctx_st(Structure):
    pass
SSL_CTX = ssl_ctx_st
class ssl_method_st(Structure):
    pass
class ssl3_enc_method(Structure):
    pass
ssl_method_st._fields_ = [
    ('version', c_int),
    ('ssl_new', CFUNCTYPE(c_int, POINTER(SSL))),
    ('ssl_clear', CFUNCTYPE(None, POINTER(SSL))),
    ('ssl_free', CFUNCTYPE(None, POINTER(SSL))),
    ('ssl_accept', CFUNCTYPE(c_int, POINTER(SSL))),
    ('ssl_connect', CFUNCTYPE(c_int, POINTER(SSL))),
    ('ssl_read', CFUNCTYPE(c_int, POINTER(SSL), c_void_p, c_int)),
    ('ssl_peek', CFUNCTYPE(c_int, POINTER(SSL), c_void_p, c_int)),
    ('ssl_write', CFUNCTYPE(c_int, POINTER(SSL), c_void_p, c_int)),
    ('ssl_shutdown', CFUNCTYPE(c_int, POINTER(SSL))),
    ('ssl_renegotiate', CFUNCTYPE(c_int, POINTER(SSL))),
    ('ssl_renegotiate_check', CFUNCTYPE(c_int, POINTER(SSL))),
    ('ssl_ctrl', CFUNCTYPE(c_long, POINTER(SSL), c_int, c_long, c_void_p)),
    ('ssl_ctx_ctrl', CFUNCTYPE(c_long, POINTER(SSL_CTX), c_int, c_long, c_void_p)),
    ('get_cipher_by_char', CFUNCTYPE(POINTER(SSL_CIPHER), POINTER(c_ubyte))),
    ('put_cipher_by_char', CFUNCTYPE(c_int, POINTER(SSL_CIPHER), POINTER(c_ubyte))),
    ('ssl_pending', CFUNCTYPE(c_int, POINTER(SSL))),
    ('num_ciphers', CFUNCTYPE(c_int)),
    ('get_cipher', CFUNCTYPE(POINTER(SSL_CIPHER), c_uint)),
    ('get_ssl_method', CFUNCTYPE(POINTER(ssl_method_st), c_int)),
    ('get_timeout', CFUNCTYPE(c_long)),
    ('ssl3_enc', POINTER(ssl3_enc_method)),
    ('ssl_version', CFUNCTYPE(c_int)),
    ('ssl_callback_ctrl', CFUNCTYPE(c_long, POINTER(SSL), c_int, CFUNCTYPE(None))),
    ('ssl_ctx_callback_ctrl', CFUNCTYPE(c_long, POINTER(SSL_CTX), c_int, CFUNCTYPE(None))),
]
assert sizeof(ssl_method_st) == 100, sizeof(ssl_method_st)
assert alignment(ssl_method_st) == 4, alignment(ssl_method_st)
ssl3_enc_method._fields_ = [
]
SSL_METHOD = ssl_method_st
class ssl_session_st(Structure):
    pass
class sess_cert_st(Structure):
    pass
ssl_session_st._fields_ = [
    ('ssl_version', c_int),
    ('key_arg_length', c_uint),
    ('key_arg', c_ubyte * 8),
    ('master_key_length', c_int),
    ('master_key', c_ubyte * 48),
    ('session_id_length', c_uint),
    ('session_id', c_ubyte * 32),
    ('sid_ctx_length', c_uint),
    ('sid_ctx', c_ubyte * 32),
    ('not_resumable', c_int),
    ('sess_cert', POINTER(sess_cert_st)),
    ('peer', POINTER(X509)),
    ('verify_result', c_long),
    ('references', c_int),
    ('timeout', c_long),
    ('time', c_long),
    ('compress_meth', c_int),
    ('cipher', POINTER(SSL_CIPHER)),
    ('cipher_id', c_ulong),
    ('ciphers', POINTER(STACK)),
    ('ex_data', CRYPTO_EX_DATA),
    ('prev', POINTER(ssl_session_st)),
    ('next', POINTER(ssl_session_st)),
]
assert sizeof(ssl_session_st) == 200, sizeof(ssl_session_st)
assert alignment(ssl_session_st) == 4, alignment(ssl_session_st)
sess_cert_st._fields_ = [
]
SSL_SESSION = ssl_session_st
GEN_SESSION_CB = CFUNCTYPE(c_int, POINTER(SSL), POINTER(c_ubyte), POINTER(c_uint))
class ssl_comp_st(Structure):
    pass
ssl_comp_st._fields_ = [
    ('id', c_int),
    ('name', STRING),
    ('method', POINTER(COMP_METHOD)),
]
assert sizeof(ssl_comp_st) == 12, sizeof(ssl_comp_st)
assert alignment(ssl_comp_st) == 4, alignment(ssl_comp_st)
SSL_COMP = ssl_comp_st
class N10ssl_ctx_st4DOLLAR_18E(Structure):
    pass
N10ssl_ctx_st4DOLLAR_18E._fields_ = [
    ('sess_connect', c_int),
    ('sess_connect_renegotiate', c_int),
    ('sess_connect_good', c_int),
    ('sess_accept', c_int),
    ('sess_accept_renegotiate', c_int),
    ('sess_accept_good', c_int),
    ('sess_miss', c_int),
    ('sess_timeout', c_int),
    ('sess_cache_full', c_int),
    ('sess_hit', c_int),
    ('sess_cb_hit', c_int),
]
assert sizeof(N10ssl_ctx_st4DOLLAR_18E) == 44, sizeof(N10ssl_ctx_st4DOLLAR_18E)
assert alignment(N10ssl_ctx_st4DOLLAR_18E) == 4, alignment(N10ssl_ctx_st4DOLLAR_18E)
class cert_st(Structure):
    pass
ssl_ctx_st._fields_ = [
    ('method', POINTER(SSL_METHOD)),
    ('cipher_list', POINTER(STACK)),
    ('cipher_list_by_id', POINTER(STACK)),
    ('cert_store', POINTER(x509_store_st)),
    ('sessions', POINTER(lhash_st)),
    ('session_cache_size', c_ulong),
    ('session_cache_head', POINTER(ssl_session_st)),
    ('session_cache_tail', POINTER(ssl_session_st)),
    ('session_cache_mode', c_int),
    ('session_timeout', c_long),
    ('new_session_cb', CFUNCTYPE(c_int, POINTER(ssl_st), POINTER(SSL_SESSION))),
    ('remove_session_cb', CFUNCTYPE(None, POINTER(ssl_ctx_st), POINTER(SSL_SESSION))),
    ('get_session_cb', CFUNCTYPE(POINTER(SSL_SESSION), POINTER(ssl_st), POINTER(c_ubyte), c_int, POINTER(c_int))),
    ('stats', N10ssl_ctx_st4DOLLAR_18E),
    ('references', c_int),
    ('app_verify_callback', CFUNCTYPE(c_int, POINTER(X509_STORE_CTX), c_void_p)),
    ('app_verify_arg', c_void_p),
    ('default_passwd_callback', POINTER(pem_password_cb)),
    ('default_passwd_callback_userdata', c_void_p),
    ('client_cert_cb', CFUNCTYPE(c_int, POINTER(SSL), POINTER(POINTER(X509)), POINTER(POINTER(EVP_PKEY)))),
    ('ex_data', CRYPTO_EX_DATA),
    ('rsa_md5', POINTER(EVP_MD)),
    ('md5', POINTER(EVP_MD)),
    ('sha1', POINTER(EVP_MD)),
    ('extra_certs', POINTER(STACK)),
    ('comp_methods', POINTER(STACK)),
    ('info_callback', CFUNCTYPE(None, POINTER(SSL), c_int, c_int)),
    ('client_CA', POINTER(STACK)),
    ('options', c_ulong),
    ('mode', c_ulong),
    ('max_cert_list', c_long),
    ('cert', POINTER(cert_st)),
    ('read_ahead', c_int),
    ('msg_callback', CFUNCTYPE(None, c_int, c_int, c_int, c_void_p, c_ulong, POINTER(SSL), c_void_p)),
    ('msg_callback_arg', c_void_p),
    ('verify_mode', c_int),
    ('verify_depth', c_int),
    ('sid_ctx_length', c_uint),
    ('sid_ctx', c_ubyte * 32),
    ('default_verify_callback', CFUNCTYPE(c_int, c_int, POINTER(X509_STORE_CTX))),
    ('generate_session_id', GEN_SESSION_CB),
    ('purpose', c_int),
    ('trust', c_int),
    ('quiet_shutdown', c_int),
]
assert sizeof(ssl_ctx_st) == 248, sizeof(ssl_ctx_st)
assert alignment(ssl_ctx_st) == 4, alignment(ssl_ctx_st)
cert_st._fields_ = [
]
class ssl2_state_st(Structure):
    pass
class ssl3_state_st(Structure):
    pass
ssl_st._fields_ = [
    ('version', c_int),
    ('type', c_int),
    ('method', POINTER(SSL_METHOD)),
    ('rbio', POINTER(BIO)),
    ('wbio', POINTER(BIO)),
    ('bbio', POINTER(BIO)),
    ('rwstate', c_int),
    ('in_handshake', c_int),
    ('handshake_func', CFUNCTYPE(c_int)),
    ('server', c_int),
    ('new_session', c_int),
    ('quiet_shutdown', c_int),
    ('shutdown', c_int),
    ('state', c_int),
    ('rstate', c_int),
    ('init_buf', POINTER(BUF_MEM)),
    ('init_msg', c_void_p),
    ('init_num', c_int),
    ('init_off', c_int),
    ('packet', POINTER(c_ubyte)),
    ('packet_length', c_uint),
    ('s2', POINTER(ssl2_state_st)),
    ('s3', POINTER(ssl3_state_st)),
    ('read_ahead', c_int),
    ('msg_callback', CFUNCTYPE(None, c_int, c_int, c_int, c_void_p, c_ulong, POINTER(SSL), c_void_p)),
    ('msg_callback_arg', c_void_p),
    ('hit', c_int),
    ('purpose', c_int),
    ('trust', c_int),
    ('cipher_list', POINTER(STACK)),
    ('cipher_list_by_id', POINTER(STACK)),
    ('enc_read_ctx', POINTER(EVP_CIPHER_CTX)),
    ('read_hash', POINTER(EVP_MD)),
    ('expand', POINTER(COMP_CTX)),
    ('enc_write_ctx', POINTER(EVP_CIPHER_CTX)),
    ('write_hash', POINTER(EVP_MD)),
    ('compress', POINTER(COMP_CTX)),
    ('cert', POINTER(cert_st)),
    ('sid_ctx_length', c_uint),
    ('sid_ctx', c_ubyte * 32),
    ('session', POINTER(SSL_SESSION)),
    ('generate_session_id', GEN_SESSION_CB),
    ('verify_mode', c_int),
    ('verify_depth', c_int),
    ('verify_callback', CFUNCTYPE(c_int, c_int, POINTER(X509_STORE_CTX))),
    ('info_callback', CFUNCTYPE(None, POINTER(SSL), c_int, c_int)),
    ('error', c_int),
    ('error_code', c_int),
    ('ctx', POINTER(SSL_CTX)),
    ('debug', c_int),
    ('verify_result', c_long),
    ('ex_data', CRYPTO_EX_DATA),
    ('client_CA', POINTER(STACK)),
    ('references', c_int),
    ('options', c_ulong),
    ('mode', c_ulong),
    ('max_cert_list', c_long),
    ('first_packet', c_int),
    ('client_version', c_int),
]
assert sizeof(ssl_st) == 268, sizeof(ssl_st)
assert alignment(ssl_st) == 4, alignment(ssl_st)
class N13ssl2_state_st4DOLLAR_19E(Structure):
    pass
N13ssl2_state_st4DOLLAR_19E._fields_ = [
    ('conn_id_length', c_uint),
    ('cert_type', c_uint),
    ('cert_length', c_uint),
    ('csl', c_uint),
    ('clear', c_uint),
    ('enc', c_uint),
    ('ccl', c_ubyte * 32),
    ('cipher_spec_length', c_uint),
    ('session_id_length', c_uint),
    ('clen', c_uint),
    ('rlen', c_uint),
]
assert sizeof(N13ssl2_state_st4DOLLAR_19E) == 72, sizeof(N13ssl2_state_st4DOLLAR_19E)
assert alignment(N13ssl2_state_st4DOLLAR_19E) == 4, alignment(N13ssl2_state_st4DOLLAR_19E)
ssl2_state_st._fields_ = [
    ('three_byte_header', c_int),
    ('clear_text', c_int),
    ('escape', c_int),
    ('ssl2_rollback', c_int),
    ('wnum', c_uint),
    ('wpend_tot', c_int),
    ('wpend_buf', POINTER(c_ubyte)),
    ('wpend_off', c_int),
    ('wpend_len', c_int),
    ('wpend_ret', c_int),
    ('rbuf_left', c_int),
    ('rbuf_offs', c_int),
    ('rbuf', POINTER(c_ubyte)),
    ('wbuf', POINTER(c_ubyte)),
    ('write_ptr', POINTER(c_ubyte)),
    ('padding', c_uint),
    ('rlength', c_uint),
    ('ract_data_length', c_int),
    ('wlength', c_uint),
    ('wact_data_length', c_int),
    ('ract_data', POINTER(c_ubyte)),
    ('wact_data', POINTER(c_ubyte)),
    ('mac_data', POINTER(c_ubyte)),
    ('read_key', POINTER(c_ubyte)),
    ('write_key', POINTER(c_ubyte)),
    ('challenge_length', c_uint),
    ('challenge', c_ubyte * 32),
    ('conn_id_length', c_uint),
    ('conn_id', c_ubyte * 16),
    ('key_material_length', c_uint),
    ('key_material', c_ubyte * 48),
    ('read_sequence', c_ulong),
    ('write_sequence', c_ulong),
    ('tmp', N13ssl2_state_st4DOLLAR_19E),
]
assert sizeof(ssl2_state_st) == 288, sizeof(ssl2_state_st)
assert alignment(ssl2_state_st) == 4, alignment(ssl2_state_st)
SSL2_STATE = ssl2_state_st
class ssl3_record_st(Structure):
    pass
ssl3_record_st._fields_ = [
    ('type', c_int),
    ('length', c_uint),
    ('off', c_uint),
    ('data', POINTER(c_ubyte)),
    ('input', POINTER(c_ubyte)),
    ('comp', POINTER(c_ubyte)),
]
assert sizeof(ssl3_record_st) == 24, sizeof(ssl3_record_st)
assert alignment(ssl3_record_st) == 4, alignment(ssl3_record_st)
SSL3_RECORD = ssl3_record_st
class ssl3_buffer_st(Structure):
    pass
size_t = __darwin_size_t
ssl3_buffer_st._fields_ = [
    ('buf', POINTER(c_ubyte)),
    ('len', size_t),
    ('offset', c_int),
    ('left', c_int),
]
assert sizeof(ssl3_buffer_st) == 16, sizeof(ssl3_buffer_st)
assert alignment(ssl3_buffer_st) == 4, alignment(ssl3_buffer_st)
SSL3_BUFFER = ssl3_buffer_st
class N13ssl3_state_st4DOLLAR_20E(Structure):
    pass
N13ssl3_state_st4DOLLAR_20E._fields_ = [
    ('cert_verify_md', c_ubyte * 72),
    ('finish_md', c_ubyte * 72),
    ('finish_md_len', c_int),
    ('peer_finish_md', c_ubyte * 72),
    ('peer_finish_md_len', c_int),
    ('message_size', c_ulong),
    ('message_type', c_int),
    ('new_cipher', POINTER(SSL_CIPHER)),
    ('dh', POINTER(DH)),
    ('next_state', c_int),
    ('reuse_message', c_int),
    ('cert_req', c_int),
    ('ctype_num', c_int),
    ('ctype', c_char * 7),
    ('ca_names', POINTER(STACK)),
    ('use_rsa_tmp', c_int),
    ('key_block_length', c_int),
    ('key_block', POINTER(c_ubyte)),
    ('new_sym_enc', POINTER(EVP_CIPHER)),
    ('new_hash', POINTER(EVP_MD)),
    ('new_compression', POINTER(SSL_COMP)),
    ('cert_request', c_int),
]
assert sizeof(N13ssl3_state_st4DOLLAR_20E) == 296, sizeof(N13ssl3_state_st4DOLLAR_20E)
assert alignment(N13ssl3_state_st4DOLLAR_20E) == 4, alignment(N13ssl3_state_st4DOLLAR_20E)
ssl3_state_st._fields_ = [
    ('flags', c_long),
    ('delay_buf_pop_ret', c_int),
    ('read_sequence', c_ubyte * 8),
    ('read_mac_secret', c_ubyte * 36),
    ('write_sequence', c_ubyte * 8),
    ('write_mac_secret', c_ubyte * 36),
    ('server_random', c_ubyte * 32),
    ('client_random', c_ubyte * 32),
    ('need_empty_fragments', c_int),
    ('empty_fragment_done', c_int),
    ('rbuf', SSL3_BUFFER),
    ('wbuf', SSL3_BUFFER),
    ('rrec', SSL3_RECORD),
    ('wrec', SSL3_RECORD),
    ('alert_fragment', c_ubyte * 2),
    ('alert_fragment_len', c_uint),
    ('handshake_fragment', c_ubyte * 4),
    ('handshake_fragment_len', c_uint),
    ('wnum', c_uint),
    ('wpend_tot', c_int),
    ('wpend_type', c_int),
    ('wpend_ret', c_int),
    ('wpend_buf', POINTER(c_ubyte)),
    ('finish_dgst1', EVP_MD_CTX),
    ('finish_dgst2', EVP_MD_CTX),
    ('change_cipher_spec', c_int),
    ('warn_alert', c_int),
    ('fatal_alert', c_int),
    ('alert_dispatch', c_int),
    ('send_alert', c_ubyte * 2),
    ('renegotiate', c_int),
    ('total_renegotiations', c_int),
    ('num_renegotiations', c_int),
    ('in_read_app_data', c_int),
    ('tmp', N13ssl3_state_st4DOLLAR_20E),
]
assert sizeof(ssl3_state_st) == 648, sizeof(ssl3_state_st)
assert alignment(ssl3_state_st) == 4, alignment(ssl3_state_st)
SSL3_STATE = ssl3_state_st
stack_st._fields_ = [
    ('num', c_int),
    ('data', POINTER(STRING)),
    ('sorted', c_int),
    ('num_alloc', c_int),
    ('comp', CFUNCTYPE(c_int, POINTER(STRING), POINTER(STRING))),
]
assert sizeof(stack_st) == 20, sizeof(stack_st)
assert alignment(stack_st) == 4, alignment(stack_st)
class ui_st(Structure):
    pass
ui_st._fields_ = [
]
UI = ui_st
class ui_method_st(Structure):
    pass
ui_method_st._fields_ = [
]
UI_METHOD = ui_method_st
class ui_string_st(Structure):
    pass
ui_string_st._fields_ = [
]
UI_STRING = ui_string_st

# values for enumeration 'UI_string_types'
UI_string_types = c_int # enum
class X509_objects_st(Structure):
    pass
X509_objects_st._fields_ = [
    ('nid', c_int),
    ('a2i', CFUNCTYPE(c_int)),
    ('i2a', CFUNCTYPE(c_int)),
]
assert sizeof(X509_objects_st) == 12, sizeof(X509_objects_st)
assert alignment(X509_objects_st) == 4, alignment(X509_objects_st)
X509_OBJECTS = X509_objects_st
X509_algor_st._fields_ = [
    ('algorithm', POINTER(ASN1_OBJECT)),
    ('parameter', POINTER(ASN1_TYPE)),
]
assert sizeof(X509_algor_st) == 8, sizeof(X509_algor_st)
assert alignment(X509_algor_st) == 4, alignment(X509_algor_st)
class X509_val_st(Structure):
    pass
X509_val_st._fields_ = [
    ('notBefore', POINTER(ASN1_TIME)),
    ('notAfter', POINTER(ASN1_TIME)),
]
assert sizeof(X509_val_st) == 8, sizeof(X509_val_st)
assert alignment(X509_val_st) == 4, alignment(X509_val_st)
X509_VAL = X509_val_st
class X509_pubkey_st(Structure):
    pass
X509_pubkey_st._fields_ = [
    ('algor', POINTER(X509_ALGOR)),
    ('public_key', POINTER(ASN1_BIT_STRING)),
    ('pkey', POINTER(EVP_PKEY)),
]
assert sizeof(X509_pubkey_st) == 12, sizeof(X509_pubkey_st)
assert alignment(X509_pubkey_st) == 4, alignment(X509_pubkey_st)
X509_PUBKEY = X509_pubkey_st
class X509_sig_st(Structure):
    pass
X509_sig_st._fields_ = [
    ('algor', POINTER(X509_ALGOR)),
    ('digest', POINTER(ASN1_OCTET_STRING)),
]
assert sizeof(X509_sig_st) == 8, sizeof(X509_sig_st)
assert alignment(X509_sig_st) == 4, alignment(X509_sig_st)
X509_SIG = X509_sig_st
class X509_name_entry_st(Structure):
    pass
X509_name_entry_st._fields_ = [
    ('object', POINTER(ASN1_OBJECT)),
    ('value', POINTER(ASN1_STRING)),
    ('set', c_int),
    ('size', c_int),
]
assert sizeof(X509_name_entry_st) == 16, sizeof(X509_name_entry_st)
assert alignment(X509_name_entry_st) == 4, alignment(X509_name_entry_st)
X509_NAME_ENTRY = X509_name_entry_st
X509_name_st._fields_ = [
    ('entries', POINTER(STACK)),
    ('modified', c_int),
    ('bytes', POINTER(BUF_MEM)),
    ('hash', c_ulong),
]
assert sizeof(X509_name_st) == 16, sizeof(X509_name_st)
assert alignment(X509_name_st) == 4, alignment(X509_name_st)
class X509_extension_st(Structure):
    pass
X509_extension_st._fields_ = [
    ('object', POINTER(ASN1_OBJECT)),
    ('critical', ASN1_BOOLEAN),
    ('value', POINTER(ASN1_OCTET_STRING)),
]
assert sizeof(X509_extension_st) == 12, sizeof(X509_extension_st)
assert alignment(X509_extension_st) == 4, alignment(X509_extension_st)
X509_EXTENSION = X509_extension_st
class x509_attributes_st(Structure):
    pass
class N18x509_attributes_st4DOLLAR_13E(Union):
    pass
N18x509_attributes_st4DOLLAR_13E._fields_ = [
    ('ptr', STRING),
    ('set', POINTER(STACK)),
    ('single', POINTER(ASN1_TYPE)),
]
assert sizeof(N18x509_attributes_st4DOLLAR_13E) == 4, sizeof(N18x509_attributes_st4DOLLAR_13E)
assert alignment(N18x509_attributes_st4DOLLAR_13E) == 4, alignment(N18x509_attributes_st4DOLLAR_13E)
x509_attributes_st._fields_ = [
    ('object', POINTER(ASN1_OBJECT)),
    ('single', c_int),
    ('value', N18x509_attributes_st4DOLLAR_13E),
]
assert sizeof(x509_attributes_st) == 12, sizeof(x509_attributes_st)
assert alignment(x509_attributes_st) == 4, alignment(x509_attributes_st)
X509_ATTRIBUTE = x509_attributes_st
class X509_req_info_st(Structure):
    pass
X509_req_info_st._fields_ = [
    ('enc', ASN1_ENCODING),
    ('version', POINTER(ASN1_INTEGER)),
    ('subject', POINTER(X509_NAME)),
    ('pubkey', POINTER(X509_PUBKEY)),
    ('attributes', POINTER(STACK)),
]
assert sizeof(X509_req_info_st) == 28, sizeof(X509_req_info_st)
assert alignment(X509_req_info_st) == 4, alignment(X509_req_info_st)
X509_REQ_INFO = X509_req_info_st
class X509_req_st(Structure):
    pass
X509_req_st._fields_ = [
    ('req_info', POINTER(X509_REQ_INFO)),
    ('sig_alg', POINTER(X509_ALGOR)),
    ('signature', POINTER(ASN1_BIT_STRING)),
    ('references', c_int),
]
assert sizeof(X509_req_st) == 16, sizeof(X509_req_st)
assert alignment(X509_req_st) == 4, alignment(X509_req_st)
X509_REQ = X509_req_st
class x509_cinf_st(Structure):
    pass
x509_cinf_st._fields_ = [
    ('version', POINTER(ASN1_INTEGER)),
    ('serialNumber', POINTER(ASN1_INTEGER)),
    ('signature', POINTER(X509_ALGOR)),
    ('issuer', POINTER(X509_NAME)),
    ('validity', POINTER(X509_VAL)),
    ('subject', POINTER(X509_NAME)),
    ('key', POINTER(X509_PUBKEY)),
    ('issuerUID', POINTER(ASN1_BIT_STRING)),
    ('subjectUID', POINTER(ASN1_BIT_STRING)),
    ('extensions', POINTER(STACK)),
]
assert sizeof(x509_cinf_st) == 40, sizeof(x509_cinf_st)
assert alignment(x509_cinf_st) == 4, alignment(x509_cinf_st)
X509_CINF = x509_cinf_st
class x509_cert_aux_st(Structure):
    pass
x509_cert_aux_st._fields_ = [
    ('trust', POINTER(STACK)),
    ('reject', POINTER(STACK)),
    ('alias', POINTER(ASN1_UTF8STRING)),
    ('keyid', POINTER(ASN1_OCTET_STRING)),
    ('other', POINTER(STACK)),
]
assert sizeof(x509_cert_aux_st) == 20, sizeof(x509_cert_aux_st)
assert alignment(x509_cert_aux_st) == 4, alignment(x509_cert_aux_st)
X509_CERT_AUX = x509_cert_aux_st
class AUTHORITY_KEYID_st(Structure):
    pass
x509_st._fields_ = [
    ('cert_info', POINTER(X509_CINF)),
    ('sig_alg', POINTER(X509_ALGOR)),
    ('signature', POINTER(ASN1_BIT_STRING)),
    ('valid', c_int),
    ('references', c_int),
    ('name', STRING),
    ('ex_data', CRYPTO_EX_DATA),
    ('ex_pathlen', c_long),
    ('ex_flags', c_ulong),
    ('ex_kusage', c_ulong),
    ('ex_xkusage', c_ulong),
    ('ex_nscert', c_ulong),
    ('skid', POINTER(ASN1_OCTET_STRING)),
    ('akid', POINTER(AUTHORITY_KEYID_st)),
    ('sha1_hash', c_ubyte * 20),
    ('aux', POINTER(X509_CERT_AUX)),
]
assert sizeof(x509_st) == 84, sizeof(x509_st)
assert alignment(x509_st) == 4, alignment(x509_st)
AUTHORITY_KEYID_st._fields_ = [
]
class x509_trust_st(Structure):
    pass
x509_trust_st._fields_ = [
    ('trust', c_int),
    ('flags', c_int),
    ('check_trust', CFUNCTYPE(c_int, POINTER(x509_trust_st), POINTER(X509), c_int)),
    ('name', STRING),
    ('arg1', c_int),
    ('arg2', c_void_p),
]
assert sizeof(x509_trust_st) == 24, sizeof(x509_trust_st)
assert alignment(x509_trust_st) == 4, alignment(x509_trust_st)
X509_TRUST = x509_trust_st
class X509_revoked_st(Structure):
    pass
X509_revoked_st._fields_ = [
    ('serialNumber', POINTER(ASN1_INTEGER)),
    ('revocationDate', POINTER(ASN1_TIME)),
    ('extensions', POINTER(STACK)),
    ('sequence', c_int),
]
assert sizeof(X509_revoked_st) == 16, sizeof(X509_revoked_st)
assert alignment(X509_revoked_st) == 4, alignment(X509_revoked_st)
X509_REVOKED = X509_revoked_st
class X509_crl_info_st(Structure):
    pass
X509_crl_info_st._fields_ = [
    ('version', POINTER(ASN1_INTEGER)),
    ('sig_alg', POINTER(X509_ALGOR)),
    ('issuer', POINTER(X509_NAME)),
    ('lastUpdate', POINTER(ASN1_TIME)),
    ('nextUpdate', POINTER(ASN1_TIME)),
    ('revoked', POINTER(STACK)),
    ('extensions', POINTER(STACK)),
    ('enc', ASN1_ENCODING),
]
assert sizeof(X509_crl_info_st) == 40, sizeof(X509_crl_info_st)
assert alignment(X509_crl_info_st) == 4, alignment(X509_crl_info_st)
X509_CRL_INFO = X509_crl_info_st
X509_crl_st._fields_ = [
    ('crl', POINTER(X509_CRL_INFO)),
    ('sig_alg', POINTER(X509_ALGOR)),
    ('signature', POINTER(ASN1_BIT_STRING)),
    ('references', c_int),
]
assert sizeof(X509_crl_st) == 16, sizeof(X509_crl_st)
assert alignment(X509_crl_st) == 4, alignment(X509_crl_st)
class private_key_st(Structure):
    pass
private_key_st._fields_ = [
    ('version', c_int),
    ('enc_algor', POINTER(X509_ALGOR)),
    ('enc_pkey', POINTER(ASN1_OCTET_STRING)),
    ('dec_pkey', POINTER(EVP_PKEY)),
    ('key_length', c_int),
    ('key_data', STRING),
    ('key_free', c_int),
    ('cipher', EVP_CIPHER_INFO),
    ('references', c_int),
]
assert sizeof(private_key_st) == 52, sizeof(private_key_st)
assert alignment(private_key_st) == 4, alignment(private_key_st)
X509_PKEY = private_key_st
class X509_info_st(Structure):
    pass
X509_info_st._fields_ = [
    ('x509', POINTER(X509)),
    ('crl', POINTER(X509_CRL)),
    ('x_pkey', POINTER(X509_PKEY)),
    ('enc_cipher', EVP_CIPHER_INFO),
    ('enc_len', c_int),
    ('enc_data', STRING),
    ('references', c_int),
]
assert sizeof(X509_info_st) == 44, sizeof(X509_info_st)
assert alignment(X509_info_st) == 4, alignment(X509_info_st)
X509_INFO = X509_info_st
class Netscape_spkac_st(Structure):
    pass
Netscape_spkac_st._fields_ = [
    ('pubkey', POINTER(X509_PUBKEY)),
    ('challenge', POINTER(ASN1_IA5STRING)),
]
assert sizeof(Netscape_spkac_st) == 8, sizeof(Netscape_spkac_st)
assert alignment(Netscape_spkac_st) == 4, alignment(Netscape_spkac_st)
NETSCAPE_SPKAC = Netscape_spkac_st
class Netscape_spki_st(Structure):
    pass
Netscape_spki_st._fields_ = [
    ('spkac', POINTER(NETSCAPE_SPKAC)),
    ('sig_algor', POINTER(X509_ALGOR)),
    ('signature', POINTER(ASN1_BIT_STRING)),
]
assert sizeof(Netscape_spki_st) == 12, sizeof(Netscape_spki_st)
assert alignment(Netscape_spki_st) == 4, alignment(Netscape_spki_st)
NETSCAPE_SPKI = Netscape_spki_st
class Netscape_certificate_sequence(Structure):
    pass
Netscape_certificate_sequence._fields_ = [
    ('type', POINTER(ASN1_OBJECT)),
    ('certs', POINTER(STACK)),
]
assert sizeof(Netscape_certificate_sequence) == 8, sizeof(Netscape_certificate_sequence)
assert alignment(Netscape_certificate_sequence) == 4, alignment(Netscape_certificate_sequence)
NETSCAPE_CERT_SEQUENCE = Netscape_certificate_sequence
class PBEPARAM_st(Structure):
    pass
PBEPARAM_st._fields_ = [
    ('salt', POINTER(ASN1_OCTET_STRING)),
    ('iter', POINTER(ASN1_INTEGER)),
]
assert sizeof(PBEPARAM_st) == 8, sizeof(PBEPARAM_st)
assert alignment(PBEPARAM_st) == 4, alignment(PBEPARAM_st)
PBEPARAM = PBEPARAM_st
class PBE2PARAM_st(Structure):
    pass
PBE2PARAM_st._fields_ = [
    ('keyfunc', POINTER(X509_ALGOR)),
    ('encryption', POINTER(X509_ALGOR)),
]
assert sizeof(PBE2PARAM_st) == 8, sizeof(PBE2PARAM_st)
assert alignment(PBE2PARAM_st) == 4, alignment(PBE2PARAM_st)
PBE2PARAM = PBE2PARAM_st
class PBKDF2PARAM_st(Structure):
    pass
PBKDF2PARAM_st._fields_ = [
    ('salt', POINTER(ASN1_TYPE)),
    ('iter', POINTER(ASN1_INTEGER)),
    ('keylength', POINTER(ASN1_INTEGER)),
    ('prf', POINTER(X509_ALGOR)),
]
assert sizeof(PBKDF2PARAM_st) == 16, sizeof(PBKDF2PARAM_st)
assert alignment(PBKDF2PARAM_st) == 4, alignment(PBKDF2PARAM_st)
PBKDF2PARAM = PBKDF2PARAM_st
class pkcs8_priv_key_info_st(Structure):
    pass
pkcs8_priv_key_info_st._fields_ = [
    ('broken', c_int),
    ('version', POINTER(ASN1_INTEGER)),
    ('pkeyalg', POINTER(X509_ALGOR)),
    ('pkey', POINTER(ASN1_TYPE)),
    ('attributes', POINTER(STACK)),
]
assert sizeof(pkcs8_priv_key_info_st) == 20, sizeof(pkcs8_priv_key_info_st)
assert alignment(pkcs8_priv_key_info_st) == 4, alignment(pkcs8_priv_key_info_st)
PKCS8_PRIV_KEY_INFO = pkcs8_priv_key_info_st
class x509_hash_dir_st(Structure):
    pass
x509_hash_dir_st._fields_ = [
    ('num_dirs', c_int),
    ('dirs', POINTER(STRING)),
    ('dirs_type', POINTER(c_int)),
    ('num_dirs_alloced', c_int),
]
assert sizeof(x509_hash_dir_st) == 16, sizeof(x509_hash_dir_st)
assert alignment(x509_hash_dir_st) == 4, alignment(x509_hash_dir_st)
X509_HASH_DIR_CTX = x509_hash_dir_st
class x509_file_st(Structure):
    pass
x509_file_st._fields_ = [
    ('num_paths', c_int),
    ('num_alloced', c_int),
    ('paths', POINTER(STRING)),
    ('path_type', POINTER(c_int)),
]
assert sizeof(x509_file_st) == 16, sizeof(x509_file_st)
assert alignment(x509_file_st) == 4, alignment(x509_file_st)
X509_CERT_FILE_CTX = x509_file_st
class x509_object_st(Structure):
    pass
class N14x509_object_st4DOLLAR_14E(Union):
    pass
N14x509_object_st4DOLLAR_14E._fields_ = [
    ('ptr', STRING),
    ('x509', POINTER(X509)),
    ('crl', POINTER(X509_CRL)),
    ('pkey', POINTER(EVP_PKEY)),
]
assert sizeof(N14x509_object_st4DOLLAR_14E) == 4, sizeof(N14x509_object_st4DOLLAR_14E)
assert alignment(N14x509_object_st4DOLLAR_14E) == 4, alignment(N14x509_object_st4DOLLAR_14E)
x509_object_st._fields_ = [
    ('type', c_int),
    ('data', N14x509_object_st4DOLLAR_14E),
]
assert sizeof(x509_object_st) == 8, sizeof(x509_object_st)
assert alignment(x509_object_st) == 4, alignment(x509_object_st)
X509_OBJECT = x509_object_st
class x509_lookup_st(Structure):
    pass
X509_LOOKUP = x509_lookup_st
class x509_lookup_method_st(Structure):
    pass
x509_lookup_method_st._fields_ = [
    ('name', STRING),
    ('new_item', CFUNCTYPE(c_int, POINTER(X509_LOOKUP))),
    ('free', CFUNCTYPE(None, POINTER(X509_LOOKUP))),
    ('init', CFUNCTYPE(c_int, POINTER(X509_LOOKUP))),
    ('shutdown', CFUNCTYPE(c_int, POINTER(X509_LOOKUP))),
    ('ctrl', CFUNCTYPE(c_int, POINTER(X509_LOOKUP), c_int, STRING, c_long, POINTER(STRING))),
    ('get_by_subject', CFUNCTYPE(c_int, POINTER(X509_LOOKUP), c_int, POINTER(X509_NAME), POINTER(X509_OBJECT))),
    ('get_by_issuer_serial', CFUNCTYPE(c_int, POINTER(X509_LOOKUP), c_int, POINTER(X509_NAME), POINTER(ASN1_INTEGER), POINTER(X509_OBJECT))),
    ('get_by_fingerprint', CFUNCTYPE(c_int, POINTER(X509_LOOKUP), c_int, POINTER(c_ubyte), c_int, POINTER(X509_OBJECT))),
    ('get_by_alias', CFUNCTYPE(c_int, POINTER(X509_LOOKUP), c_int, STRING, c_int, POINTER(X509_OBJECT))),
]
assert sizeof(x509_lookup_method_st) == 40, sizeof(x509_lookup_method_st)
assert alignment(x509_lookup_method_st) == 4, alignment(x509_lookup_method_st)
X509_LOOKUP_METHOD = x509_lookup_method_st
x509_store_st._fields_ = [
    ('cache', c_int),
    ('objs', POINTER(STACK)),
    ('get_cert_methods', POINTER(STACK)),
    ('flags', c_ulong),
    ('purpose', c_int),
    ('trust', c_int),
    ('verify', CFUNCTYPE(c_int, POINTER(X509_STORE_CTX))),
    ('verify_cb', CFUNCTYPE(c_int, c_int, POINTER(X509_STORE_CTX))),
    ('get_issuer', CFUNCTYPE(c_int, POINTER(POINTER(X509)), POINTER(X509_STORE_CTX), POINTER(X509))),
    ('check_issued', CFUNCTYPE(c_int, POINTER(X509_STORE_CTX), POINTER(X509), POINTER(X509))),
    ('check_revocation', CFUNCTYPE(c_int, POINTER(X509_STORE_CTX))),
    ('get_crl', CFUNCTYPE(c_int, POINTER(X509_STORE_CTX), POINTER(POINTER(X509_CRL)), POINTER(X509))),
    ('check_crl', CFUNCTYPE(c_int, POINTER(X509_STORE_CTX), POINTER(X509_CRL))),
    ('cert_crl', CFUNCTYPE(c_int, POINTER(X509_STORE_CTX), POINTER(X509_CRL), POINTER(X509))),
    ('cleanup', CFUNCTYPE(c_int, POINTER(X509_STORE_CTX))),
    ('ex_data', CRYPTO_EX_DATA),
    ('references', c_int),
    ('depth', c_int),
]
assert sizeof(x509_store_st) == 76, sizeof(x509_store_st)
assert alignment(x509_store_st) == 4, alignment(x509_store_st)
x509_lookup_st._fields_ = [
    ('init', c_int),
    ('skip', c_int),
    ('method', POINTER(X509_LOOKUP_METHOD)),
    ('method_data', STRING),
    ('store_ctx', POINTER(X509_STORE)),
]
assert sizeof(x509_lookup_st) == 20, sizeof(x509_lookup_st)
assert alignment(x509_lookup_st) == 4, alignment(x509_lookup_st)
time_t = __darwin_time_t
x509_store_ctx_st._fields_ = [
    ('ctx', POINTER(X509_STORE)),
    ('current_method', c_int),
    ('cert', POINTER(X509)),
    ('untrusted', POINTER(STACK)),
    ('purpose', c_int),
    ('trust', c_int),
    ('check_time', time_t),
    ('flags', c_ulong),
    ('other_ctx', c_void_p),
    ('verify', CFUNCTYPE(c_int, POINTER(X509_STORE_CTX))),
    ('verify_cb', CFUNCTYPE(c_int, c_int, POINTER(X509_STORE_CTX))),
    ('get_issuer', CFUNCTYPE(c_int, POINTER(POINTER(X509)), POINTER(X509_STORE_CTX), POINTER(X509))),
    ('check_issued', CFUNCTYPE(c_int, POINTER(X509_STORE_CTX), POINTER(X509), POINTER(X509))),
    ('check_revocation', CFUNCTYPE(c_int, POINTER(X509_STORE_CTX))),
    ('get_crl', CFUNCTYPE(c_int, POINTER(X509_STORE_CTX), POINTER(POINTER(X509_CRL)), POINTER(X509))),
    ('check_crl', CFUNCTYPE(c_int, POINTER(X509_STORE_CTX), POINTER(X509_CRL))),
    ('cert_crl', CFUNCTYPE(c_int, POINTER(X509_STORE_CTX), POINTER(X509_CRL), POINTER(X509))),
    ('cleanup', CFUNCTYPE(c_int, POINTER(X509_STORE_CTX))),
    ('depth', c_int),
    ('valid', c_int),
    ('last_untrusted', c_int),
    ('chain', POINTER(STACK)),
    ('error_depth', c_int),
    ('error', c_int),
    ('current_cert', POINTER(X509)),
    ('current_issuer', POINTER(X509)),
    ('current_crl', POINTER(X509_CRL)),
    ('ex_data', CRYPTO_EX_DATA),
]
assert sizeof(x509_store_ctx_st) == 116, sizeof(x509_store_ctx_st)
assert alignment(x509_store_ctx_st) == 4, alignment(x509_store_ctx_st)
va_list = __darwin_va_list
__darwin_off_t = __int64_t
fpos_t = __darwin_off_t
class __sbuf(Structure):
    pass
__sbuf._fields_ = [
    ('_base', POINTER(c_ubyte)),
    ('_size', c_int),
]
assert sizeof(__sbuf) == 8, sizeof(__sbuf)
assert alignment(__sbuf) == 4, alignment(__sbuf)
class __sFILEX(Structure):
    pass
__sFILEX._fields_ = [
]
class __sFILE(Structure):
    pass
__sFILE._pack_ = 4
__sFILE._fields_ = [
    ('_p', POINTER(c_ubyte)),
    ('_r', c_int),
    ('_w', c_int),
    ('_flags', c_short),
    ('_file', c_short),
    ('_bf', __sbuf),
    ('_lbfsize', c_int),
    ('_cookie', c_void_p),
    ('_close', CFUNCTYPE(c_int, c_void_p)),
    ('_read', CFUNCTYPE(c_int, c_void_p, STRING, c_int)),
    ('_seek', CFUNCTYPE(fpos_t, c_void_p, c_longlong, c_int)),
    ('_write', CFUNCTYPE(c_int, c_void_p, STRING, c_int)),
    ('_ub', __sbuf),
    ('_extra', POINTER(__sFILEX)),
    ('_ur', c_int),
    ('_ubuf', c_ubyte * 3),
    ('_nbuf', c_ubyte * 1),
    ('_lb', __sbuf),
    ('_blksize', c_int),
    ('_offset', fpos_t),
]
assert sizeof(__sFILE) == 88, sizeof(__sFILE)
assert alignment(__sFILE) == 4, alignment(__sFILE)
FILE = __sFILE
ct_rune_t = __darwin_ct_rune_t
rune_t = __darwin_rune_t
class div_t(Structure):
    pass
div_t._fields_ = [
    ('quot', c_int),
    ('rem', c_int),
]
assert sizeof(div_t) == 8, sizeof(div_t)
assert alignment(div_t) == 4, alignment(div_t)
class ldiv_t(Structure):
    pass
ldiv_t._fields_ = [
    ('quot', c_long),
    ('rem', c_long),
]
assert sizeof(ldiv_t) == 8, sizeof(ldiv_t)
assert alignment(ldiv_t) == 4, alignment(ldiv_t)
class lldiv_t(Structure):
    pass
lldiv_t._pack_ = 4
lldiv_t._fields_ = [
    ('quot', c_longlong),
    ('rem', c_longlong),
]
assert sizeof(lldiv_t) == 16, sizeof(lldiv_t)
assert alignment(lldiv_t) == 4, alignment(lldiv_t)
__darwin_dev_t = __int32_t
dev_t = __darwin_dev_t
__darwin_mode_t = __uint16_t
mode_t = __darwin_mode_t
class mcontext(Structure):
    pass
mcontext._fields_ = [
]
class mcontext64(Structure):
    pass
mcontext64._fields_ = [
]
class __darwin_pthread_handler_rec(Structure):
    pass
__darwin_pthread_handler_rec._fields_ = [
    ('__routine', CFUNCTYPE(None, c_void_p)),
    ('__arg', c_void_p),
    ('__next', POINTER(__darwin_pthread_handler_rec)),
]
assert sizeof(__darwin_pthread_handler_rec) == 12, sizeof(__darwin_pthread_handler_rec)
assert alignment(__darwin_pthread_handler_rec) == 4, alignment(__darwin_pthread_handler_rec)
class _opaque_pthread_attr_t(Structure):
    pass
_opaque_pthread_attr_t._fields_ = [
    ('__sig', c_long),
    ('__opaque', c_char * 36),
]
assert sizeof(_opaque_pthread_attr_t) == 40, sizeof(_opaque_pthread_attr_t)
assert alignment(_opaque_pthread_attr_t) == 4, alignment(_opaque_pthread_attr_t)
class _opaque_pthread_cond_t(Structure):
    pass
_opaque_pthread_cond_t._fields_ = [
    ('__sig', c_long),
    ('__opaque', c_char * 24),
]
assert sizeof(_opaque_pthread_cond_t) == 28, sizeof(_opaque_pthread_cond_t)
assert alignment(_opaque_pthread_cond_t) == 4, alignment(_opaque_pthread_cond_t)
class _opaque_pthread_condattr_t(Structure):
    pass
_opaque_pthread_condattr_t._fields_ = [
    ('__sig', c_long),
    ('__opaque', c_char * 4),
]
assert sizeof(_opaque_pthread_condattr_t) == 8, sizeof(_opaque_pthread_condattr_t)
assert alignment(_opaque_pthread_condattr_t) == 4, alignment(_opaque_pthread_condattr_t)
class _opaque_pthread_mutex_t(Structure):
    pass
_opaque_pthread_mutex_t._fields_ = [
    ('__sig', c_long),
    ('__opaque', c_char * 40),
]
assert sizeof(_opaque_pthread_mutex_t) == 44, sizeof(_opaque_pthread_mutex_t)
assert alignment(_opaque_pthread_mutex_t) == 4, alignment(_opaque_pthread_mutex_t)
class _opaque_pthread_mutexattr_t(Structure):
    pass
_opaque_pthread_mutexattr_t._fields_ = [
    ('__sig', c_long),
    ('__opaque', c_char * 8),
]
assert sizeof(_opaque_pthread_mutexattr_t) == 12, sizeof(_opaque_pthread_mutexattr_t)
assert alignment(_opaque_pthread_mutexattr_t) == 4, alignment(_opaque_pthread_mutexattr_t)
class _opaque_pthread_once_t(Structure):
    pass
_opaque_pthread_once_t._fields_ = [
    ('__sig', c_long),
    ('__opaque', c_char * 4),
]
assert sizeof(_opaque_pthread_once_t) == 8, sizeof(_opaque_pthread_once_t)
assert alignment(_opaque_pthread_once_t) == 4, alignment(_opaque_pthread_once_t)
class _opaque_pthread_rwlock_t(Structure):
    pass
_opaque_pthread_rwlock_t._fields_ = [
    ('__sig', c_long),
    ('__opaque', c_char * 124),
]
assert sizeof(_opaque_pthread_rwlock_t) == 128, sizeof(_opaque_pthread_rwlock_t)
assert alignment(_opaque_pthread_rwlock_t) == 4, alignment(_opaque_pthread_rwlock_t)
class _opaque_pthread_rwlockattr_t(Structure):
    pass
_opaque_pthread_rwlockattr_t._fields_ = [
    ('__sig', c_long),
    ('__opaque', c_char * 12),
]
assert sizeof(_opaque_pthread_rwlockattr_t) == 16, sizeof(_opaque_pthread_rwlockattr_t)
assert alignment(_opaque_pthread_rwlockattr_t) == 4, alignment(_opaque_pthread_rwlockattr_t)
class _opaque_pthread_t(Structure):
    pass
_opaque_pthread_t._fields_ = [
    ('__sig', c_long),
    ('__cleanup_stack', POINTER(__darwin_pthread_handler_rec)),
    ('__opaque', c_char * 596),
]
assert sizeof(_opaque_pthread_t) == 604, sizeof(_opaque_pthread_t)
assert alignment(_opaque_pthread_t) == 4, alignment(_opaque_pthread_t)
__darwin_blkcnt_t = __int64_t
__darwin_blksize_t = __int32_t
__darwin_fsblkcnt_t = c_uint
__darwin_fsfilcnt_t = c_uint
__darwin_gid_t = __uint32_t
__darwin_id_t = __uint32_t
__darwin_ino_t = __uint32_t
__darwin_mach_port_name_t = __darwin_natural_t
__darwin_mach_port_t = __darwin_mach_port_name_t
__darwin_mcontext_t = POINTER(mcontext)
__darwin_mcontext64_t = POINTER(mcontext64)
__darwin_pid_t = __int32_t
__darwin_pthread_attr_t = _opaque_pthread_attr_t
__darwin_pthread_cond_t = _opaque_pthread_cond_t
__darwin_pthread_condattr_t = _opaque_pthread_condattr_t
__darwin_pthread_key_t = c_ulong
__darwin_pthread_mutex_t = _opaque_pthread_mutex_t
__darwin_pthread_mutexattr_t = _opaque_pthread_mutexattr_t
__darwin_pthread_once_t = _opaque_pthread_once_t
__darwin_pthread_rwlock_t = _opaque_pthread_rwlock_t
__darwin_pthread_rwlockattr_t = _opaque_pthread_rwlockattr_t
__darwin_pthread_t = POINTER(_opaque_pthread_t)
__darwin_sigset_t = __uint32_t
__darwin_suseconds_t = __int32_t
__darwin_uid_t = __uint32_t
__darwin_useconds_t = __uint32_t
__darwin_uuid_t = c_ubyte * 16
class sigaltstack(Structure):
    pass
sigaltstack._fields_ = [
    ('ss_sp', c_void_p),
    ('ss_size', __darwin_size_t),
    ('ss_flags', c_int),
]
assert sizeof(sigaltstack) == 12, sizeof(sigaltstack)
assert alignment(sigaltstack) == 4, alignment(sigaltstack)
__darwin_stack_t = sigaltstack
class ucontext(Structure):
    pass
ucontext._fields_ = [
    ('uc_onstack', c_int),
    ('uc_sigmask', __darwin_sigset_t),
    ('uc_stack', __darwin_stack_t),
    ('uc_link', POINTER(ucontext)),
    ('uc_mcsize', __darwin_size_t),
    ('uc_mcontext', __darwin_mcontext_t),
]
assert sizeof(ucontext) == 32, sizeof(ucontext)
assert alignment(ucontext) == 4, alignment(ucontext)
__darwin_ucontext_t = ucontext
class ucontext64(Structure):
    pass
ucontext64._fields_ = [
    ('uc_onstack', c_int),
    ('uc_sigmask', __darwin_sigset_t),
    ('uc_stack', __darwin_stack_t),
    ('uc_link', POINTER(ucontext64)),
    ('uc_mcsize', __darwin_size_t),
    ('uc_mcontext64', __darwin_mcontext64_t),
]
assert sizeof(ucontext64) == 32, sizeof(ucontext64)
assert alignment(ucontext64) == 4, alignment(ucontext64)
__darwin_ucontext64_t = ucontext64
class timeval(Structure):
    pass
timeval._fields_ = [
    ('tv_sec', __darwin_time_t),
    ('tv_usec', __darwin_suseconds_t),
]
assert sizeof(timeval) == 8, sizeof(timeval)
assert alignment(timeval) == 4, alignment(timeval)
rlim_t = __int64_t
class rusage(Structure):
    pass
rusage._fields_ = [
    ('ru_utime', timeval),
    ('ru_stime', timeval),
    ('ru_maxrss', c_long),
    ('ru_ixrss', c_long),
    ('ru_idrss', c_long),
    ('ru_isrss', c_long),
    ('ru_minflt', c_long),
    ('ru_majflt', c_long),
    ('ru_nswap', c_long),
    ('ru_inblock', c_long),
    ('ru_oublock', c_long),
    ('ru_msgsnd', c_long),
    ('ru_msgrcv', c_long),
    ('ru_nsignals', c_long),
    ('ru_nvcsw', c_long),
    ('ru_nivcsw', c_long),
]
assert sizeof(rusage) == 72, sizeof(rusage)
assert alignment(rusage) == 4, alignment(rusage)
class rlimit(Structure):
    pass
rlimit._pack_ = 4
rlimit._fields_ = [
    ('rlim_cur', rlim_t),
    ('rlim_max', rlim_t),
]
assert sizeof(rlimit) == 16, sizeof(rlimit)
assert alignment(rlimit) == 4, alignment(rlimit)
mcontext_t = __darwin_mcontext_t
mcontext64_t = __darwin_mcontext64_t
pthread_attr_t = __darwin_pthread_attr_t
sigset_t = __darwin_sigset_t
ucontext_t = __darwin_ucontext_t
ucontext64_t = __darwin_ucontext64_t
uid_t = __darwin_uid_t
class sigval(Union):
    pass
sigval._fields_ = [
    ('sival_int', c_int),
    ('sival_ptr', c_void_p),
]
assert sizeof(sigval) == 4, sizeof(sigval)
assert alignment(sigval) == 4, alignment(sigval)
class sigevent(Structure):
    pass
sigevent._fields_ = [
    ('sigev_notify', c_int),
    ('sigev_signo', c_int),
    ('sigev_value', sigval),
    ('sigev_notify_function', CFUNCTYPE(None, sigval)),
    ('sigev_notify_attributes', POINTER(pthread_attr_t)),
]
assert sizeof(sigevent) == 20, sizeof(sigevent)
assert alignment(sigevent) == 4, alignment(sigevent)
class __siginfo(Structure):
    pass
pid_t = __darwin_pid_t
__siginfo._fields_ = [
    ('si_signo', c_int),
    ('si_errno', c_int),
    ('si_code', c_int),
    ('si_pid', pid_t),
    ('si_uid', uid_t),
    ('si_status', c_int),
    ('si_addr', c_void_p),
    ('si_value', sigval),
    ('si_band', c_long),
    ('pad', c_ulong * 7),
]
assert sizeof(__siginfo) == 64, sizeof(__siginfo)
assert alignment(__siginfo) == 4, alignment(__siginfo)
siginfo_t = __siginfo
class __sigaction_u(Union):
    pass
__sigaction_u._fields_ = [
    ('__sa_handler', CFUNCTYPE(None, c_int)),
    ('__sa_sigaction', CFUNCTYPE(None, c_int, POINTER(__siginfo), c_void_p)),
]
assert sizeof(__sigaction_u) == 4, sizeof(__sigaction_u)
assert alignment(__sigaction_u) == 4, alignment(__sigaction_u)
class __sigaction(Structure):
    pass
__sigaction._fields_ = [
    ('__sigaction_u', __sigaction_u),
    ('sa_tramp', CFUNCTYPE(None, c_void_p, c_int, c_int, POINTER(siginfo_t), c_void_p)),
    ('sa_mask', sigset_t),
    ('sa_flags', c_int),
]
assert sizeof(__sigaction) == 16, sizeof(__sigaction)
assert alignment(__sigaction) == 4, alignment(__sigaction)
class sigaction(Structure):
    pass
sigaction._fields_ = [
    ('__sigaction_u', __sigaction_u),
    ('sa_mask', sigset_t),
    ('sa_flags', c_int),
]
assert sizeof(sigaction) == 12, sizeof(sigaction)
assert alignment(sigaction) == 4, alignment(sigaction)
sig_t = CFUNCTYPE(None, c_int)
stack_t = __darwin_stack_t
class sigvec(Structure):
    pass
sigvec._fields_ = [
    ('sv_handler', CFUNCTYPE(None, c_int)),
    ('sv_mask', c_int),
    ('sv_flags', c_int),
]
assert sizeof(sigvec) == 12, sizeof(sigvec)
assert alignment(sigvec) == 4, alignment(sigvec)
class sigstack(Structure):
    pass
sigstack._fields_ = [
    ('ss_sp', STRING),
    ('ss_onstack', c_int),
]
assert sizeof(sigstack) == 8, sizeof(sigstack)
assert alignment(sigstack) == 4, alignment(sigstack)
u_char = c_ubyte
u_short = c_ushort
u_int = c_uint
u_long = c_ulong
ushort = c_ushort
uint = c_uint
u_quad_t = u_int64_t
quad_t = int64_t
qaddr_t = POINTER(quad_t)
caddr_t = STRING
daddr_t = int32_t
fixpt_t = u_int32_t
blkcnt_t = __darwin_blkcnt_t
blksize_t = __darwin_blksize_t
gid_t = __darwin_gid_t
in_addr_t = __uint32_t
in_port_t = __uint16_t
ino_t = __darwin_ino_t
key_t = __int32_t
nlink_t = __uint16_t
off_t = __darwin_off_t
segsz_t = int32_t
swblk_t = int32_t
clock_t = __darwin_clock_t
ssize_t = __darwin_ssize_t
useconds_t = __darwin_useconds_t
suseconds_t = __darwin_suseconds_t
fd_mask = __int32_t
class fd_set(Structure):
    pass
fd_set._fields_ = [
    ('fds_bits', __int32_t * 32),
]
assert sizeof(fd_set) == 128, sizeof(fd_set)
assert alignment(fd_set) == 4, alignment(fd_set)
pthread_cond_t = __darwin_pthread_cond_t
pthread_condattr_t = __darwin_pthread_condattr_t
pthread_mutex_t = __darwin_pthread_mutex_t
pthread_mutexattr_t = __darwin_pthread_mutexattr_t
pthread_once_t = __darwin_pthread_once_t
pthread_rwlock_t = __darwin_pthread_rwlock_t
pthread_rwlockattr_t = __darwin_pthread_rwlockattr_t
pthread_t = __darwin_pthread_t
pthread_key_t = __darwin_pthread_key_t
fsblkcnt_t = __darwin_fsblkcnt_t
fsfilcnt_t = __darwin_fsfilcnt_t

# values for enumeration 'idtype_t'
idtype_t = c_int # enum
id_t = __darwin_id_t
class wait(Union):
    pass
class N4wait3DOLLAR_3E(Structure):
    pass
N4wait3DOLLAR_3E._fields_ = [
    ('w_Termsig', c_uint, 7),
    ('w_Coredump', c_uint, 1),
    ('w_Retcode', c_uint, 8),
    ('w_Filler', c_uint, 16),
]
assert sizeof(N4wait3DOLLAR_3E) == 4, sizeof(N4wait3DOLLAR_3E)
assert alignment(N4wait3DOLLAR_3E) == 4, alignment(N4wait3DOLLAR_3E)
class N4wait3DOLLAR_4E(Structure):
    pass
N4wait3DOLLAR_4E._fields_ = [
    ('w_Stopval', c_uint, 8),
    ('w_Stopsig', c_uint, 8),
    ('w_Filler', c_uint, 16),
]
assert sizeof(N4wait3DOLLAR_4E) == 4, sizeof(N4wait3DOLLAR_4E)
assert alignment(N4wait3DOLLAR_4E) == 4, alignment(N4wait3DOLLAR_4E)
wait._fields_ = [
    ('w_status', c_int),
    ('w_T', N4wait3DOLLAR_3E),
    ('w_S', N4wait3DOLLAR_4E),
]
assert sizeof(wait) == 4, sizeof(wait)
assert alignment(wait) == 4, alignment(wait)
class timespec(Structure):
    pass
timespec._fields_ = [
    ('tv_sec', time_t),
    ('tv_nsec', c_long),
]
assert sizeof(timespec) == 8, sizeof(timespec)
assert alignment(timespec) == 4, alignment(timespec)
class tm(Structure):
    pass
tm._fields_ = [
    ('tm_sec', c_int),
    ('tm_min', c_int),
    ('tm_hour', c_int),
    ('tm_mday', c_int),
    ('tm_mon', c_int),
    ('tm_year', c_int),
    ('tm_wday', c_int),
    ('tm_yday', c_int),
    ('tm_isdst', c_int),
    ('tm_gmtoff', c_long),
    ('tm_zone', STRING),
]
assert sizeof(tm) == 44, sizeof(tm)
assert alignment(tm) == 4, alignment(tm)
__gnuc_va_list = STRING
ptrdiff_t = c_int
int8_t = c_byte
int16_t = c_short
uint8_t = c_ubyte
uint16_t = c_ushort
uint32_t = c_uint
uint64_t = c_ulonglong
int_least8_t = int8_t
int_least16_t = int16_t
int_least32_t = int32_t
int_least64_t = int64_t
uint_least8_t = uint8_t
uint_least16_t = uint16_t
uint_least32_t = uint32_t
uint_least64_t = uint64_t
int_fast8_t = int8_t
int_fast16_t = int16_t
int_fast32_t = int32_t
int_fast64_t = int64_t
uint_fast8_t = uint8_t
uint_fast16_t = uint16_t
uint_fast32_t = uint32_t
uint_fast64_t = uint64_t
intptr_t = c_long
uintptr_t = c_ulong
intmax_t = c_longlong
uintmax_t = c_ulonglong
__all__ = ['ENGINE', 'pkcs7_enc_content_st', '__int16_t',
           'X509_REVOKED', 'SSL_CTX', 'UIT_BOOLEAN',
           '__darwin_time_t', 'ucontext64_t', 'int_fast32_t',
           'pem_ctx_st', 'uint8_t', 'fpos_t', 'X509', 'COMP_CTX',
           'tm', 'N10pem_ctx_st4DOLLAR_17E', 'swblk_t',
           'ASN1_TEMPLATE', '__darwin_pthread_t', 'fixpt_t',
           'BIO_METHOD', 'ASN1_PRINTABLESTRING', 'EVP_ENCODE_CTX',
           'dh_method', 'bio_f_buffer_ctx_struct', 'in_port_t',
           'X509_SIG', '__darwin_ssize_t', '__darwin_sigset_t',
           'wait', 'uint_fast16_t', 'N12asn1_type_st4DOLLAR_11E',
           'uint_least8_t', 'pthread_rwlock_t', 'ASN1_IA5STRING',
           'fsfilcnt_t', 'ucontext', '__uint64_t', 'timespec',
           'x509_cinf_st', 'COMP_METHOD', 'MD5_CTX', 'buf_mem_st',
           'ASN1_ENCODING_st', 'PBEPARAM', 'X509_NAME_ENTRY',
           '__darwin_va_list', 'ucontext_t', 'lhash_st',
           'N4wait3DOLLAR_4E', '__darwin_uuid_t',
           '_ossl_old_des_ks_struct', 'id_t', 'ASN1_BIT_STRING',
           'va_list', '__darwin_wchar_t', 'pthread_key_t',
           'pkcs7_signer_info_st', 'ASN1_METHOD', 'DSA_SIG', 'DSA',
           'UIT_NONE', 'pthread_t', '__darwin_useconds_t',
           'uint_fast8_t', 'UI_STRING', 'DES_cblock',
           '__darwin_mcontext64_t', 'rlim_t', 'PEM_Encode_Seal_st',
           'SHAstate_st', 'u_quad_t', 'openssl_fptr',
           '_opaque_pthread_rwlockattr_t',
           'N18x509_attributes_st4DOLLAR_13E',
           '__darwin_pthread_rwlock_t', 'daddr_t', 'ui_string_st',
           'x509_file_st', 'X509_req_info_st', 'int_least64_t',
           'evp_Encode_Ctx_st', 'X509_OBJECTS', 'CRYPTO_EX_DATA',
           '__int8_t', 'AUTHORITY_KEYID_st', '_opaque_pthread_attr_t',
           'sigstack', 'EVP_CIPHER_CTX', 'X509_extension_st', 'pid_t',
           'RSA_METHOD', 'PEM_USER', 'pem_recip_st', 'env_md_ctx_st',
           'rc5_key_st', 'ui_st', 'X509_PUBKEY', 'u_int8_t',
           'ASN1_ITEM_st', 'pkcs7_recip_info_st', 'ssl2_state_st',
           'off_t', 'N10ssl_ctx_st4DOLLAR_18E', 'crypto_ex_data_st',
           'ui_method_st', '__darwin_pthread_rwlockattr_t',
           'CRYPTO_EX_dup', '__darwin_ino_t', '__sFILE',
           'OSUnknownByteOrder', 'BN_MONT_CTX', 'ASN1_NULL', 'time_t',
           'CRYPTO_EX_new', 'asn1_type_st', 'CRYPTO_EX_DATA_FUNCS',
           'user_time_t', 'BIGNUM', 'pthread_rwlockattr_t',
           'ASN1_VALUE_st', 'DH_METHOD', '__darwin_off_t',
           '_opaque_pthread_t', 'bn_blinding_st', 'RSA', 'ssize_t',
           'mcontext64_t', 'user_long_t', 'fsblkcnt_t', 'cert_st',
           '__darwin_pthread_condattr_t', 'X509_PKEY',
           '__darwin_id_t', '__darwin_nl_item', 'SSL2_STATE', 'FILE',
           'pthread_mutexattr_t', 'size_t',
           '_ossl_old_des_key_schedule', 'pkcs7_issuer_and_serial_st',
           'sigval', 'CRYPTO_MEM_LEAK_CB', 'X509_NAME', 'blkcnt_t',
           'uint_least16_t', '__darwin_dev_t', 'evp_cipher_info_st',
           'BN_BLINDING', 'ssl3_state_st', 'uint_least64_t',
           'user_addr_t', 'DES_key_schedule', 'RIPEMD160_CTX',
           'u_char', 'X509_algor_st', 'uid_t', 'sess_cert_st',
           'u_int64_t', 'u_int16_t', 'sigset_t', '__darwin_ptrdiff_t',
           'ASN1_CTX', 'STACK', '__int32_t', 'UI_METHOD',
           'NETSCAPE_SPKI', 'UIT_PROMPT', 'st_CRYPTO_EX_DATA_IMPL',
           'cast_key_st', 'X509_HASH_DIR_CTX', 'sigevent',
           'user_ssize_t', 'clock_t', 'aes_key_st',
           '__darwin_socklen_t', '__darwin_intptr_t', 'int_fast64_t',
           'asn1_string_table_st', 'uint_fast32_t',
           'ASN1_VISIBLESTRING', 'DSA_SIG_st', 'obj_name_st',
           'X509_LOOKUP_METHOD', 'u_int32_t', 'EVP_CIPHER_INFO',
           '__gnuc_va_list', 'AES_KEY', 'PKCS7_ISSUER_AND_SERIAL',
           'BN_CTX', '__darwin_blkcnt_t', 'key_t', 'SHA_CTX',
           'pkcs7_signed_st', 'SSL', 'N10pem_ctx_st4DOLLAR_16E',
           'pthread_attr_t', 'EVP_MD', 'uint', 'ASN1_BOOLEAN',
           'ino_t', '__darwin_clock_t', 'ASN1_OCTET_STRING',
           'asn1_ctx_st', 'BIO_F_BUFFER_CTX', 'bn_mont_ctx_st',
           'X509_REQ_INFO', 'PEM_CTX', 'sigvec',
           '__darwin_pthread_mutexattr_t', 'x509_attributes_st',
           'stack_t', '__darwin_mode_t', '__mbstate_t',
           'asn1_object_st', 'ASN1_ENCODING', '__uint8_t',
           'LHASH_NODE', 'PKCS7_SIGNER_INFO', 'asn1_method_st',
           'stack_st', 'bio_info_cb', 'div_t', 'UIT_VERIFY',
           'PBEPARAM_st', 'N4wait3DOLLAR_3E', 'quad_t', '__siginfo',
           '__darwin_mbstate_t', 'rsa_st', 'ASN1_UNIVERSALSTRING',
           'uint64_t', 'ssl_comp_st', 'X509_OBJECT', 'pthread_cond_t',
           'DH', '__darwin_wctype_t', 'PKCS7_ENVELOPE', 'ASN1_TLC_st',
           'sig_atomic_t', 'BIO', 'nlink_t', 'BUF_MEM', 'SSL3_RECORD',
           'bio_method_st', 'timeval', 'UI_string_types', 'BIO_dummy',
           'ssl_ctx_st', 'NETSCAPE_CERT_SEQUENCE',
           'BIT_STRING_BITNAME_st', '__darwin_pthread_attr_t',
           'int8_t', '__darwin_wint_t', 'OBJ_NAME',
           'PKCS8_PRIV_KEY_INFO', 'PBE2PARAM_st',
           'LHASH_DOALL_FN_TYPE', 'x509_st', 'X509_VAL', 'dev_t',
           'ASN1_TEMPLATE_st', 'MD5state_st', '__uint16_t',
           'LHASH_DOALL_ARG_FN_TYPE', 'mdc2_ctx_st', 'SSL3_STATE',
           'ssl3_buffer_st', 'ASN1_ITEM_EXP',
           '_opaque_pthread_condattr_t', 'mode_t', 'ASN1_VALUE',
           'qaddr_t', '__darwin_gid_t', 'EVP_PKEY', 'CRYPTO_EX_free',
           '_ossl_old_des_cblock', 'X509_INFO', 'asn1_string_st',
           'intptr_t', 'UIT_INFO', 'int_fast8_t', 'sigaltstack',
           'env_md_st', 'LHASH', '__darwin_ucontext_t',
           'PKCS7_SIGN_ENVELOPE', '__darwin_mcontext_t', 'ct_rune_t',
           'MD2_CTX', 'pthread_once_t', 'SSL3_BUFFER', 'fd_mask',
           'ASN1_TYPE', 'PKCS7_SIGNED', 'ssl3_record_st', 'BF_KEY',
           'MD4state_st', 'MD4_CTX', 'int16_t', 'SSL_CIPHER',
           'rune_t', 'X509_TRUST', 'siginfo_t', 'X509_STORE',
           '__sbuf', 'X509_STORE_CTX', '__darwin_blksize_t', 'ldiv_t',
           'ASN1_TIME', 'SSL_METHOD', 'X509_LOOKUP',
           'Netscape_spki_st', 'P_PID', 'sigaction', 'sig_t',
           'hostent', 'x509_cert_aux_st', '_opaque_pthread_cond_t',
           'segsz_t', 'ushort', '__darwin_ct_rune_t', 'fd_set',
           'BN_RECP_CTX', 'x509_lookup_st', 'uint16_t', 'pkcs7_st',
           'asn1_header_st', '__darwin_pthread_key_t',
           'x509_trust_st', '__darwin_pthread_handler_rec', 'int32_t',
           'X509_CRL_INFO', 'N11evp_pkey_st4DOLLAR_12E', 'MDC2_CTX',
           'N23_ossl_old_des_ks_struct4DOLLAR_10E', 'ASN1_HEADER',
           'X509_crl_info_st', 'LHASH_HASH_FN_TYPE',
           '_opaque_pthread_mutexattr_t', 'ssl_st',
           'N8pkcs7_st4DOLLAR_15E', 'evp_pkey_st',
           'pkcs7_signedandenveloped_st', '__darwin_mach_port_t',
           'EVP_PBE_KEYGEN', '_opaque_pthread_mutex_t',
           'ASN1_UTCTIME', 'mcontext', 'crypto_ex_data_func_st',
           'u_long', 'PBKDF2PARAM_st', 'rc4_key_st', 'DSA_METHOD',
           'EVP_CIPHER', 'BIT_STRING_BITNAME', 'PKCS7_RECIP_INFO',
           'ssl3_enc_method', 'X509_CERT_AUX', 'uintmax_t',
           'int_fast16_t', 'RC5_32_KEY', 'ucontext64', 'ASN1_INTEGER',
           'u_short', 'N14x509_object_st4DOLLAR_14E', 'mcontext64',
           'X509_sig_st', 'ASN1_GENERALSTRING', 'PKCS7', '__sFILEX',
           'X509_name_entry_st', 'ssl_session_st', 'caddr_t',
           'bignum_st', 'X509_CINF', '__darwin_pthread_cond_t',
           'ASN1_TLC', 'PKCS7_ENCRYPT', 'NETSCAPE_SPKAC',
           'Netscape_spkac_st', 'idtype_t', 'UIT_ERROR',
           'uint_fast64_t', 'in_addr_t', 'pthread_mutex_t',
           '__int64_t', 'ASN1_BMPSTRING', 'uint32_t',
           'PEM_ENCODE_SEAL_CTX', 'suseconds_t', 'ASN1_OBJECT',
           'X509_val_st', 'private_key_st', 'CRYPTO_dynlock',
           'X509_objects_st', 'CRYPTO_EX_DATA_IMPL',
           'pthread_condattr_t', 'PKCS7_DIGEST', 'uint_least32_t',
           'ASN1_STRING', '__uint32_t', 'P_PGID', 'rsa_meth_st',
           'X509_crl_st', 'RC2_KEY', '__darwin_fsfilcnt_t',
           'X509_revoked_st', 'PBE2PARAM', 'blksize_t',
           'Netscape_certificate_sequence', 'ssl_cipher_st',
           'bignum_ctx', 'register_t', 'ASN1_UTF8STRING',
           'pkcs7_encrypted_st', 'RC4_KEY', '__darwin_ucontext64_t',
           'N13ssl2_state_st4DOLLAR_19E', 'bn_recp_ctx_st',
           'CAST_KEY', 'X509_ATTRIBUTE', '__darwin_suseconds_t',
           '__sigaction', 'user_ulong_t', 'syscall_arg_t',
           'evp_cipher_ctx_st', 'X509_ALGOR', 'mcontext_t',
           'const_DES_cblock', '__darwin_fsblkcnt_t', 'dsa_st',
           'int_least8_t', 'MD2state_st', 'X509_EXTENSION',
           'GEN_SESSION_CB', 'int_least16_t', '__darwin_wctrans_t',
           'PBKDF2PARAM', 'x509_lookup_method_st', 'pem_password_cb',
           'X509_info_st', 'x509_store_st', '__darwin_natural_t',
           'X509_pubkey_st', 'pkcs7_digest_st', '__darwin_size_t',
           'ASN1_STRING_TABLE', 'OSLittleEndian', 'RIPEMD160state_st',
           'pkcs7_enveloped_st', 'UI', 'ptrdiff_t', 'X509_REQ',
           'CRYPTO_dynlock_value', 'X509_req_st', 'x509_store_ctx_st',
           'N13ssl3_state_st4DOLLAR_20E', 'lhash_node_st',
           '__darwin_pthread_mutex_t', 'LHASH_COMP_FN_TYPE',
           '__darwin_rune_t', 'rlimit', '__darwin_pthread_once_t',
           'OSBigEndian', 'uintptr_t', '__darwin_uid_t', 'u_int',
           'ASN1_T61STRING', 'gid_t', 'ssl_method_st', 'ASN1_ITEM',
           'ASN1_ENUMERATED', '_opaque_pthread_rwlock_t',
           'pkcs8_priv_key_info_st', 'intmax_t', 'sigcontext',
           'X509_CRL', 'rc2_key_st', 'engine_st', 'x509_object_st',
           '_opaque_pthread_once_t', 'DES_ks', 'SSL_COMP',
           'dsa_method', 'int64_t', 'bio_st', 'bf_key_st',
           'ASN1_GENERALIZEDTIME', 'PKCS7_ENC_CONTENT',
           '__darwin_pid_t', 'lldiv_t', 'comp_method_st',
           'EVP_MD_CTX', 'evp_cipher_st', 'X509_name_st',
           'x509_hash_dir_st', '__darwin_mach_port_name_t',
           'useconds_t', 'user_size_t', 'SSL_SESSION', 'rusage',
           'ssl_crock_st', 'int_least32_t', '__sigaction_u', 'dh_st',
           'P_ALL', '__darwin_stack_t', 'N6DES_ks3DOLLAR_9E',
           'comp_ctx_st', 'X509_CERT_FILE_CTX']
