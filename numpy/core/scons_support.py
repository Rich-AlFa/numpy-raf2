from os.path import join as pjoin, dirname as pdirname, basename as pbasename

from code_generators.generate_array_api import \
        types, h_template as multiarray_h_template, \
        c_template as multiarray_c_template
from code_generators.generate_ufunc_api import \
        h_template as ufunc_h_template, \
        c_template as ufunc_c_template
import code_generators.genapi as genapi

import SCons.Errors

# XXX: better refactor code_generators.generate* functions, and use them
# directly
def do_generate_api(target, source, env):
    """source has to be a sequence of OBJECT, MULTIARRAY txt files."""
    h_file = str(target[0])
    c_file = str(target[1])
    t_file = str(target[2])

    if not len(source) == 2:
        # XXX
        assert 0 == 1
    OBJECT_API_ORDER = str(source[0])
    MULTIARRAY_API_ORDER = str(source[1])
    objectapi_list = genapi.get_api_functions('OBJECT_API',
                                              OBJECT_API_ORDER)
    multiapi_list = genapi.get_api_functions('MULTIARRAY_API',
                                             MULTIARRAY_API_ORDER)
    # API fixes for __arrayobject_api.h

    fixed = 10
    numtypes = len(types) + fixed
    numobject = len(objectapi_list) + numtypes
    nummulti = len(multiapi_list)
    numtotal = numobject + nummulti

    module_list = []
    extension_list = []
    init_list = []

    # setup types
    for k, atype in enumerate(types):
        num = fixed + k
        astr = "        (void *) &Py%sArrType_Type," % types[k]
        init_list.append(astr)
        astr = "static PyTypeObject Py%sArrType_Type;" % types[k]
        module_list.append(astr)
        astr = "#define Py%sArrType_Type (*(PyTypeObject *)PyArray_API[%d])" % \
               (types[k], num)
        extension_list.append(astr)

    # set up object API
    genapi.add_api_list(numtypes, 'PyArray_API', objectapi_list,
                        module_list, extension_list, init_list)

    # set up multiarray module API
    genapi.add_api_list(numobject, 'PyArray_API', multiapi_list,
                        module_list, extension_list, init_list)


    # Write to header
    fid = open(h_file, 'w')
    s = multiarray_h_template % ('\n'.join(module_list), '\n'.join(extension_list))
    fid.write(s)
    fid.close()

    # Write to c-code
    fid = open(c_file, 'w')
    s = multiarray_c_template % '\n'.join(init_list)
    fid.write(s)
    fid.close()

    # write to documentation
    fid = open(t_file, 'w')
    fid.write('''
===========
Numpy C-API
===========

Object API
==========
''')
    for func in objectapi_list:
        fid.write(func.to_ReST())
        fid.write('\n\n')
    fid.write('''

Multiarray API
==============
''')
    for func in multiapi_list:
        fid.write(func.to_ReST())
        fid.write('\n\n')
    fid.close()

    return 0

def generate_api_emitter(target, source, env):
    """Returns the list of targets generated by the code generator for array api."""
    base, ext = SCons.Util.splitext(str(target[0]))
    dir = pdirname(base)
    ba = pbasename(base)
    h = pjoin(dir, '__' + ba + '.h')
    c = pjoin(dir, '__' + ba + '.c')
    txt = base + '.txt'
    print h, c, txt
    t = [h, c, txt]
    return (t, source)

def do_generate_ufunc_api(target, source, env):
    """source has to be a txt file."""
    h_file = str(target[0])
    c_file = str(target[1])
    d_file = str(target[2])

    targets = (h_file, c_file, d_file)

    UFUNC_API_ORDER = str(source[0])
    ufunc_api_list = genapi.get_api_functions('UFUNC_API', UFUNC_API_ORDER)

    # API fixes for __arrayobject_api.h

    fixed = 1
    nummulti = len(ufunc_api_list)
    numtotal = fixed + nummulti

    module_list = []
    extension_list = []
    init_list = []

    # set up object API
    genapi.add_api_list(fixed, 'PyUFunc_API', ufunc_api_list,
                        module_list, extension_list, init_list)

    # Write to header
    fid = open(h_file, 'w')
    s = ufunc_h_template % ('\n'.join(module_list), '\n'.join(extension_list))
    fid.write(s)
    fid.close()

    # Write to c-code
    fid = open(c_file, 'w')
    s = ufunc_c_template % '\n'.join(init_list)
    fid.write(s)
    fid.close()

    # Write to documentation
    fid = open(d_file, 'w')
    fid.write('''
=================
Numpy Ufunc C-API
=================
''')
    for func in ufunc_api_list:
        fid.write(func.to_ReST())
        fid.write('\n\n')
    fid.close()

    return 0
