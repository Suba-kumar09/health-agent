from agent.crypto import FieldCipher, NullCipher


def test_field_cipher_round_trip():
    key = FieldCipher.generate_key()
    cipher = FieldCipher(key)
    data = {"keypress_count": 42, "active_secs": 30}

    token = cipher.encrypt_json(data)

    assert token != data
    assert cipher.decrypt_json(token) == data


def test_field_cipher_requires_correct_key():
    cipher_a = FieldCipher(FieldCipher.generate_key())
    cipher_b = FieldCipher(FieldCipher.generate_key())
    token = cipher_a.encrypt_json({"x": 1})

    try:
        cipher_b.decrypt_json(token)
        assert False, "expected decryption to fail with wrong key"
    except Exception:
        pass


def test_null_cipher_round_trip():
    cipher = NullCipher()
    data = {"a": 1}
    assert cipher.decrypt_json(cipher.encrypt_json(data)) == data
