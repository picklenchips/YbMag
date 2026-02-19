# ~/bin/env python3
"""
General utility functions for formatting, typing, file management, timing. 
"""
import time, os, warnings, functools
from typing import Sequence, Iterable, Any
import numpy as np
from itertools import zip_longest

INT = int | np.integer
FLOAT = float | np.floating
REAL = INT | FLOAT
COMPLEX = complex | np.complexfloating
NUMBER = REAL | COMPLEX

TO_METRIC = {
    -24: "y",  # yotto
    -21: "z",  # zepto
    -18: "a",  # atto
    -15: "f",  # femto
    -12: "p",  # pico
    -9: "n",  # nano
    -6: "µ",  # micro
    -3: "m",  # milli
    0: "",  #
    3: "k",  # kilo
    6: "M",  # mega
    9: "G",  # giga
    12: "T",  # tera
    15: "P",  # peta
    18: "E",  # exa
    21: "Z",  # zetta
    24: "Y",  # yotta
}
FROM_METRIC = {v: k for k, v in TO_METRIC.items()}
FROM_METRIC["u"] = -6
FROM_METRIC["meg"] = FROM_METRIC["Meg"] = 6


def ensure_new_file(fpath: str):
    """
    returns new `fpath=f(_i).ext` by incrementing `f(_i).ext` -> `f_{i+1}.ext` until new file is found.
    e.g. `f.ext` -> `f_0.ext` -> `f_1.ext` -> ...
    """
    # convert from relative to absolute path
    dirname, filename = os.path.split(fpath)  # 'dirname', 'basename.ext'
    basename, ext = os.path.splitext(filename)  # 'basename', '.ext'
    lastnum = 0
    pre, post = dirname + os.sep + basename, ext  # 'dirname/basename', '.ext'
    # find last number in basename of form "name_<int>"
    i = basename.rfind("_")
    if i == -1:  # no underscore found
        pre += "_"
    elif i + 1 == len(basename):  # underscore at end
        fpath = pre[:-1] + post
    elif basename[i + 1 :].isdigit():
        # cut to 'dirname/base_'
        lastnum = int(basename[i + 1 :])
        pre = dirname + os.sep + basename[: i + 1]
    else:
        pre += "_"  # add underscore if no number found
    if not os.path.exists(fpath):
        return fpath  # if no-number version exists, return "raw" filename
    while os.path.exists(pre + str(lastnum) + post):
        lastnum += 1  # increment last number until file is unique
    return pre + str(lastnum) + post


def timeIt(_func=None, *, repeat=1, return_time=False, print_time=False):
    """Wrapper to time a function with various return options.

    Args
    ----
    repeat: int
        will average the function runtime by repeating it `repeat` times
    return_time: bool
        returns (ret, time) if True, else just ret
    print_time: bool
        prints time to stdout if True

    .. note::
        Arguments MUST be given as keyword arguments to a wrapper function, the first arg is always assumed to be the function that is being wrapped.

    Examples
    --------
    .. code-block:: python

        repeat: int = 10
        return_time: bool = True
        @timeIt(repeat=repeat, return_time=return_time)
        def f(*args, **kwargs):
            ...
            return ret

    >>> print(f(*args, **kwargs))
    (ret, mean_time_in_seconds)

    .. code-block:: python

            repeat: int = 10
            return_time: bool = True
            @timeIt(repeat=repeat, return_time=return_time)
            def f(*args, **kwargs):
                ...
                return ret

    >>> ret = f(*args, **kwargs)
    f ran in 0.123s, averaged over 10 times

    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            total_time = 0
            for i in range(repeat):
                # changed from time.clock_gettime()
                # for windows compatibility
                start_time = time.time()
                ret = func(*args, **kwargs)
                total_time += time.time() - start_time
            mean_time = total_time / repeat
            msg = f"{func.__name__} took {uFormat(mean_time, metric=True)}s"
            if repeat > 1:
                msg += f", avg of {repeat} times"
            if print_time:
                print(msg)
            if return_time:
                return ret, mean_time
            return ret

        return wrapper

    if _func is None:
        return decorator
    return decorator(_func)


def alignNumbers(numbers: Sequence[str], inplace=False, figs=3) -> list[str]:
    """
    Aligns numbers in a list of strings so that the decimal points are in the same column and all numbers have the same string length by adding spaces before and after the numbers.

    Args
    ----
    numbers: Iterable[str]
        list of strings to align
    inplace: bool
        if True, modifies the original list of strings in place
    """
    if isinstance(numbers, np.ndarray):
        numbers = numbers.tolist()
    if not isinstance(numbers, (list,)):
        raise TypeError("numbers must be a list or tuple of strings")
    if not all(isinstance(n, str) for n in numbers):
        raise TypeError("numbers must be a list or tuple of strings")
    # find the maximum length of the strings
    lengths = np.array([len(n) for n in numbers])
    # find the index of the decimal point in each string
    decimal_indices = np.empty(len(numbers), dtype=int)
    for i, n in enumerate(numbers):
        if decimal_indices[i] == -1:
            for char in [".", "(", "e", " "]:
                if (j := n.find(char)) != -1:
                    decimal_indices[i] = j
                    break
        if decimal_indices[i] == -1:
            decimal_indices[i] = min(figs, len(n))
    # find max chars before and after decimal point, and align
    befores = max(decimal_indices) - decimal_indices
    decimal_indices_r = lengths - decimal_indices
    afters = max(decimal_indices_r) - decimal_indices_r
    aligned_numbers = []
    # add spaces before and after the number to align it
    for i in range(len(numbers)):
        aligned_number = (
            " " * befores[i] + numbers[i] + " " * (afters[i] if afters[i] >= 0 else 0)
        )
        if inplace:
            numbers[i] = aligned_number
        else:
            aligned_numbers.append(aligned_number)
    return aligned_numbers if not inplace else numbers


def uFormat(
    number: REAL | str | Iterable[REAL | str],
    uncertainty: str | REAL | Iterable[REAL | str] = 0.0,
    figs: INT | Iterable[INT] = 4,
    shift: INT | Iterable[INT] = 0,
    ndecs: INT | Iterable[INT] = -1,
    math: bool | Iterable[bool] = False,
    metric: bool | Iterable[bool] = False,
    percent: bool | Iterable[bool] = False,
    metric_space=True,
    debug=False,
    join_string=", ",
    align_all=False,
    align_function=alignNumbers,
    format_function=None,
) -> str:
    r"""
    Formats a number with its uncertainty, according to `PDG §5.3 <https://pdg.lbl.gov/2011/reviews/rpp2011-rev-rpp-intro.pdf#page=13>`_ rules. Also handles other formatting options, see below.

    Args
    ----
    number:
        the value to format, converted to a float
    uncertainty:
        the absolute uncertainty (stddev) in the value
        * if zero, will format number according to `figs`
    figs:
        when `uncertainty == 0`, formats number to this # of significant figures. default 4.
    shift:
        shift the resultant number to a higher/lower digit expression
        * i.e. if number is in Hz and you want a string in GHz, specify `shift = 9`
        * likewise for going from MHz to Hz, specify `shift = -6`
    ndecs:
        cuts off the number to at most this many decimal places, like `:.2f` would be `ndecs=2`
    math:
        LaTeX format: output "X.XX\text{e-D}" since "-" will render as a minus sign otherwise
        .. note:: to print correctly, you must make sure the string is RAW r''
    metric:
        will correctly label number using metric prefixes (see :py:dict:`METRIC_PREFIXES`) based on scale of number
        * ex: `1.23e6 -> 1.23 M`, or `0.03 -> 30 m`
        .. note:: make sure to put a unit at the end of the string for real quantities!
    percent:
        will treat number as a percentage and add a "%" at the end, automatically
        shifting the number by 2 to the left
        * ex: `0.03 -> 3%` and `3 -> 300%`
    join_string:
        if ANY of the arguments are Iterable, will map uFormat to the arguments as appropriate and
        join them with join_string
        * e.g. number = (1.0, 2.0, 3.0), uncertainty = (0.1, 0.2, 0.3), join_string = "." will return "1(1).2(2).3(3)"
    align_all:
        if True, will align all numbers (iterable arguments given) so that decimal places are in the same column by adding spaces before and after the number
        * this is useful for printing tables of numbers
    align_function:
        function to use for aligning numbers. default is :func:`align_numbers`
    format_function:
        additional function to format the output of uFormat. takes in a string and returns a string.

    Returns
    -------
    str: the formatted number as a string

    Examples
    --------
    >>> uFormat(0.01264, 0.0023)
    '0.013(2)'
    >>> uFormat(0.001234, 0.00067)
    '1.234(67)e-3'
    >>> uFormat(0.0006789, 0.000023, metric=True)
    '679(23) µ'
    >>> uFormat(0.306, 0.02, percent=True, math=True)
    '31(2)\%'
    >>> uFormat(32849, 5000, metric=True, math=True)
    '33(5)\text{ k}'
    >>> uFormat(0.00048388, figs=3)
    '4.84e-4'
    >>> uFormat((0.001, 0.002), metric=((True, False),False), percent=(False, True))
    '1 µ, 1e-3, 0.2%'

    Notes
    ------
    * if both `metric` and `percent` are specified, will raise ValueError, as these formatting options conflict!
    * able to handle any arguments as (nested) iterables, if given.

        * this will copy the last value of shorter-length arguments to match the longest-length argument, so be careful!
        * for example, `metric=((True, False),)` and `percent=(False, True)` will raise an error because this will map to `metric=((True, False),(True, False))` and `percent=(False, True)`, which contradicts on the 3rd call.

    * best way to specify different metric/percent formatting is to use same-length iterables.

        * e.g. metric=(False, True, True), percent=(False, False, True)

    """
    # if any of the arguments are iterable, apply uFormat to each element
    # and join them with join_string
    # if join_string is not specified and arguments are iterable, will raise a value error
    # this is actually also able to handle nested iterables, if given.

    kwargs_per_iter = []
    # valid iterable arguments
    kwargs = {
        "number": number,
        "uncertainty": uncertainty,
        "figs": figs,
        "shift": shift,
        "ndecs": ndecs,
        "math": math,
        "metric": metric,
        "percent": percent,
    }
    kwargs["debug"] = debug
    for arg, argval in kwargs.items():
        if hasattr(argval, "__iter__") and not isinstance(argval, str):
            for i, v in enumerate(argval):
                if i >= len(kwargs_per_iter):
                    kwargs_per_iter.append({})
                kwargs_per_iter[i][arg] = v
    # if ANY of the arguments are iterable, apply uFormat over each argument
    if len(kwargs_per_iter) > 0:
        if debug:
            print(kwargs_per_iter)
        # place single args into the first dictionary
        ret = []
        for i in range(len(kwargs_per_iter)):
            kwargs.update(kwargs_per_iter[i])
            ret.append(uFormat(**kwargs))
        # format the output strings if align is true
        if align_all:
            # set uniform figs to max for alignment... could use min?
            if isinstance(figs, Iterable):
                figs = max(figs)
            align_function(ret, inplace=True, figs=int(figs))  # type: ignore
        return join_string.join(ret)
    # else, just apply uFormat to the single number
    # at this point, all arguments are single values
    assert isinstance(figs, INT)
    assert isinstance(shift, INT)
    assert isinstance(ndecs, INT)
    # using separate variables here for the type checker, which somehow doesn't register the type assertions above
    # SHOULD compile away, right??
    _figs = int(figs)
    _shift = int(shift)
    _ndecs = int(ndecs)
    if metric and percent:
        raise ValueError(
            "Cannot have both metric and percent formatting! See docstring for formatting info."
        )
    num = str(number)
    err = str(uncertainty)
    if _figs < 1:
        _figs = 1
    ignore_uncertainty = not uncertainty  # UNCERTAINTY ZERO: IN SIG FIGS MODE

    is_negative = False  # add back negative later
    if num[0] == "-":
        num = num[1:]
        is_negative = True
    if err[0] == "-":
        err = err[1:]

    # ni = NUM DIGITS to the RIGHT of DECIMAL
    # 0.00001234=1.234e-4 has ni = 8, 4 digs after decimal and 4 sig figs
    # 1234 w/ ni=5 corresponds to 0.01234
    # 1234 w/ ni=-4 corresponds to 12340000 = 1234e7, n - ni - 1 = 7
    ni = ei = 0

    def get_raw_number(num: str) -> tuple[str, int]:
        """returns raw_num, idx where raw_num contains all significant figures of number and idx is the magnitude of the rightmost digit of the number"""
        found_sigfig = False
        found_decimal = False
        index_right_of_decimal = 0
        raw_num = ""
        # scientific notation
        if "e" in num:
            ff = num.split("e")
            num = ff[0]
            index_right_of_decimal = -int(ff[1])
        for ch in num:
            if found_decimal:
                index_right_of_decimal += 1
            if not found_sigfig and ch == "0":  # dont care ab leading zeroes
                # TODO: any scenario in which we want to conserve leading zeros?
                continue
            if ch == ".":
                found_decimal = True
                continue
            if not ch.isdigit():
                return "?", 0
            found_sigfig = True
            raw_num += ch
        return raw_num, index_right_of_decimal

    def round_to_idx(string: str, idx: int) -> str:
        """rounds string to idx significant figures"""
        if idx >= len(string):
            return string
        if int(string[idx]) >= 5:
            return str(int(string[:idx]) + 1)
        return string[:idx]

    # get raw numbers
    raw_num, ni = get_raw_number(num)
    # only cut to ndecimals, like :.2f
    if _ndecs > -1 and ni > _ndecs:
        diff = ni - _ndecs
        n = len(raw_num)
        dec_to_cut = n - diff + 1
        if diff > n:
            return "0"
        if dec_to_cut > 0 and dec_to_cut < n:
            ni = _ndecs + 1
            raw_num = raw_num[:dec_to_cut]
            _figs = min(_figs, dec_to_cut - 1) if ignore_uncertainty else dec_to_cut - 1
            if _figs < 1:  # no figures are left before ndecimals!
                return "0"
    if raw_num == "?":
        return str(num)
        # raise ValueError(f"input number {number} is not a valid number!")
    n = len(raw_num)
    if n == 0:  # our number contains only zeros!
        return "0"
    raw_err, ei = get_raw_number(err)
    if raw_err == "?":
        print(f"input error {uncertainty} is not a valid number, continuing anyways...")
    m = len(raw_err)
    if m == 0:  # our error contains only zeros!
        ignore_uncertainty = True
    # 0.01234 -> '1234', (4, 5)
    if debug and ignore_uncertainty:
        print("ignoring uncertainty!")
    #
    # round error according to PDG rules
    # consider only three significant figures of error
    #
    if m > 3:
        ei += 3 - m
        raw_err = raw_err[:3]
    if m > 1:
        # have 3 digits in error, round correctly according to PDG
        if m == 2:
            raw_err += "0"
            ei += 1
        # round error correctly according to PDG
        err_three = int(raw_err)
        # 123 -> (12.)
        if err_three < 355:
            raw_err = round_to_idx(raw_err, 2)
            ei -= 1
        # 950 -> (10..)
        elif err_three > 949:
            raw_err = "10"
            ei -= 2
        # 355 -> (4..)
        else:
            raw_err = round_to_idx(raw_err, 1)
            ei -= 2
        m = len(raw_err)
    # round to sig figs!!
    if ignore_uncertainty:
        assert m == 0
        assert not raw_err
        ei = min(ni, ni - n + _figs)
    # figs is now rounded for sig figs!!
    if _ndecs > -1 and ni > _ndecs:
        ei = min(ei, ni - n + _figs)
    # shift numbers, if specified
    if percent:
        _shift += 2
    ni -= _shift
    ei -= _shift
    #
    # round number according to error
    # n = number of significant digits in number
    # ni = magnitude of rightmost digit in number
    # mag_num = magnitude of leftmost digit in number
    # eg: 0.0023 -> 2.3e-3, n=2, ni=4, mag_num=-3
    # place of 1st digit in number (scientific notation of number)
    mag_num = n - ni - 1
    mag_err = m - ei - 1
    d = ni - ei
    # format number according to metric prefixes
    end = ""
    if debug:
        print("pre-metric:")
        print(f"'{raw_num}' {n}_{ni}({mag_num}) '{raw_err}' {m}_{ei}({mag_err})")
        print("post metric:")
    if metric:
        b = int(np.floor(mag_num / 3))
        # only up to e24 and down to e-24
        if abs(b) > 8:
            b = 0
        # equivalent to c = mag_num % 3
        c = mag_num - b * 3  # either of 0,1,2
        prefix = TO_METRIC[b * 3]
        # 0.0003 -> 0.000300, so real ni is now c - mag_num = 2 - (-4) = 6 instead of 4
        # c - mag_num is the digit to the left of the position of the metric decimal
        real_ni = ni
        ni = max(ni, c - mag_num)
        added_zeros = ni - real_ni
        raw_num = raw_num + "0" * added_zeros
        final_ni = (c - mag_num) - ni
        # add "ghost zeros" to error if necessary
        if c - mag_num > ei:
            if not ignore_uncertainty:
                raw_err = raw_err + "~" * (c - mag_num - ei)
            ei += c - mag_num - ei
        # 0.003 -> 3 m, b = -1, c = 0
        # 0.0003333 -> 333.3 µ, b = -2, c = 2
        # 0.00003 -> 30 µ, b = -2, c = 1
        # change formatting to metric formatting
        end = prefix
        if debug:
            print(
                f"c={c}, b={b}, prefix={prefix}, real_ni={real_ni}, final_ni={final_ni}"
            )
    if debug:
        print(f"'{raw_num}' {n}_{ni}({mag_num}) '{raw_err}' {m}_{ei}({mag_err})")
    # this is position of LEFTmost digit
    # ni, ei are positions of RIGHTmost digit
    # now round NUMBER to ERROR
    if mag_err > mag_num:
        # num = 0.0012345 -- n=5, ni = 3, mag = -3 = n - ni - 1
        # err = 0.019
        # uncertainty is a magnitude larger than number, still format number
        if not ignore_uncertainty:
            warnings.warn(
                f"Uncrtnty: {uncertainty} IS MAGNITUDE(S) > THAN Numba: {number}"
            )
        raw_err = "?"
        m = len(raw_err)
    elif ni > ei:
        # num = 0.00012345 --> 1235(23)  (note the rounding of 12345->12350)
        # err = 0.00023
        raw_num = round_to_idx(raw_num, n - (ni - ei))
        n = len(raw_num)
        ni = ei
    elif ni < ei:
        if ni > ei - m:
            # there is some overlap...
            # num = 0.000300  --> 1.2345(2)e-3
            # err = 0.000238
            raw_err = round_to_idx(raw_err, m + d)
            m = len(raw_err)
            ei = ni
        else:
            # num = 0.000100  --> 1.2345e-3
            # err = 0.000000234
            raw_err = ""
    elif ni == ei and not metric:
        # raw_err = ""
        pass
    if metric:
        ni = ni - (c - mag_num)
    if debug:
        print("post rounding:")
        print(f"'{raw_num}' {n}_{ni}({mag_num}) '{raw_err}' {m}_{ei}({mag_err})")
    extra_ni = 0
    # final form saves space by converting to scientific notation 0.0023 -> 2.3e-3
    if not _shift and not percent and (ni - n) >= 2:
        extra_ni = ni - n + 1
        ni = n - 1
    if debug:
        print("final conversion:")
        print(f"'{raw_num}' {n}_{ni}({mag_num}) '{raw_err}' {m}_{ei}({mag_err})")
    # FINAL number formatting according to n and ni
    if ni >= n:  # place decimal before any digits
        raw_num = "0." + "0" * (ni - n) + raw_num
    elif ni > 0:  # place decimal in-between digits
        raw_num = raw_num[: n - ni] + "." + raw_num[n - ni :]
    elif ni < 0 and not metric:  # add non-significant zeroes after number (POSITIVE e)
        # if e1, want to just add 2 zeros
        if ni > -2:
            raw_num += "0" * (-ni)
            if ei > -2 and raw_err:
                raw_err += "0" * (-ei)
        else:
            end = "e" + str(-ni)
    if extra_ni and not metric:  # format removed decimal zeroes  (NEGATIVE e)
        end = "e" + str(-extra_ni)
    if metric and metric_space:
        end = " " + end
    if end and math:  # format for LaTeX
        end = r"\text{" + end + "}"
    if percent:
        if math:
            end += "\\"
        end += "%"
    if is_negative:  # add back negative
        raw_num = "-" + raw_num
    if raw_err and not ignore_uncertainty:
        end = "(" + raw_err + ")" + end
    out = raw_num + end
    if format_function is not None:
        return format_function(out)
    return out


def format_to_short(thing, maxlenstr=4):
    """Formats various types to short string representations of length <= maxlenstr."""
    if isinstance(thing, bool):
        return "T" if thing else "F"
    if isinstance(thing, str):
        return thing.lower().replace("_", "-")[:maxlenstr]
    if isinstance(thing, FLOAT):
        # format first 3 sig figs, along with metric prefix
        return uFormat(thing, 0, min(maxlenstr - 1, 1), metric=True, metric_space=False)
    # recursively format iterables
    if hasattr(thing, "__iter__"):
        things = list(map(format_to_short, thing))
        # if all are equal, just output first one
        if all([thing == things[0] for thing in things]):
            return things[0]
        return "-".join(things)
    representation = str(thing)
    # for functions, just return the last part of the name
    if representation.startswith("<"):
        return format_to_short(thing.__name__)
    # or else we don't know what to do...
    return format_to_short(representation)


def format_dictlist_tree(
    d: dict[Any, list[Any]],
    keys: list[str] | None = None,
    tablength=2,
    indentstr="-",
    formatindent=lambda x: f"|{x}> ",
    formatrow=lambda x: f"{x}",
    joinstr="\t",
    format_vals=format_to_short,
    joinval_str=", ",
    format_keys=lambda x: f"{x}",
    keyvals_sep=" : ",
    join_first=True,
):
    """format a dictionary of lists as left-aligned tree of lists"""
    if not len(d):
        return ""  # no keys!
    if keys is None or not len(keys):
        keys = list(d.keys())
    keys_len = [
        len(indentstr * tablength * i + format_keys(key)) for i, key in enumerate(keys)
    ]
    maxlen = max(keys_len)
    all_vals = [[len(format_vals(val)) for val in d[key]] for key in keys]
    # for each column of all_vals (rows have possibly different lengths), zip the col items together from all len(all_vals) rows
    # and find the max length of each column
    collens = [
        max([(val if val else 0) for val in col]) for col in zip_longest(*all_vals)
    ]
    flist = [
        f"{formatindent(indentstr * tablength * (i + 1))}{format_keys(key):<{maxlen - tablength*i}}{keyvals_sep}"
        + joinval_str.join(
            f"{format_vals(val)}" + " " * (collens[j] - all_vals[i][j])
            for j, val in enumerate(d[key])
        )
        for i, key in enumerate(keys)
    ]
    if join_first:
        flist[0] = joinstr + flist[0]
    return ("\n" + joinstr).join(formatrow(f) for f in flist)
